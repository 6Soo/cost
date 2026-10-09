"""런타임 상태 집계가 관측과 판정을 갈라 세는지 합성 대역만으로 확인한다.

운영 파일이나 네트워크는 건드리지 않는다. 권한 원본, DB, HTTP 조사는 모두
합성 대역이다. 여행 권위 검증·분류·보류·운영 접근 코드는 바꾸지 않는다.
"""
import unittest
from types import SimpleNamespace

from tools import verify_lightweight_runtime as verify


def flow_stub(trips, *, valid_ids, visible=0, integrity='ok',
              counts=(('classified', 2), ('needs_review', 1)), batches=('b1',)):
    """읽기 전용으로 보이는 CardFlow 대역."""
    class Cursor:
        """`fetchone`/`fetchall`만 가진 읽기 전용 커서 대역."""
        def __init__(self, rows):
            self._rows=iter(rows)

        def fetchone(self):
            return next(self._rows, None)

        def fetchall(self):
            return list(self._rows)

        def __iter__(self):
            return self._rows

    def execute(sql, *args):
        if 'GROUP BY classification_state' in sql:
            rows=tuple(counts)
        elif 'COUNT(*) FROM transactions' in sql:
            rows=((len(trips),),)
        elif 'COUNT(*) FROM import_batches' in sql:
            rows=((len(batches),),)
        elif 'COUNT(*) FROM board_rows' in sql:
            rows=((1,),)
        elif 'review_source_guidance' in sql:
            rows=((2,),)
        elif 'decision_events' in sql:
            rows=((3,),)
        elif 'integrity_check' in sql:
            rows=((integrity,),)
        elif 'import_batches' in sql:
            rows=tuple((batch,) for batch in batches)
        else:
            raise AssertionError('unexpected query: '+sql)
        return Cursor(rows)
    board=SimpleNamespace(conn=SimpleNamespace(execute=execute),
                          path='synthetic-board.sqlite',
                          list_trips=lambda:trips)
    return SimpleNamespace(board=board,
                           trip_valid=lambda tab_id:tab_id in valid_ids,
                           state=lambda batch:{'rows':[{}]*visible})


class StatusCountsWaitingTripsWithoutFailing(unittest.TestCase):
    def test_some_trips_waiting_for_authority_is_still_healthy(self):
        trips=[{'tab_id':'t1','display_key':'alpha'},{'tab_id':'t2','display_key':'beta'},
               {'tab_id':'t3','display_key':'gamma'}]
        flow=flow_stub(trips,valid_ids={'t1','t2'},batches=('b1',))
        status=verify.collect_runtime_status(
            flow,config={'decisions_db_path':'synthetic-board.sqlite'},
            routes=(),probe=lambda route:0)
        self.assertEqual(status['trip_count'],3)
        self.assertEqual(status['verified_trip_count'],2)
        self.assertEqual(status['invalid_trip_count'],1)
        self.assertFalse(status['schedule_validation_complete'])
        self.assertEqual(status['waiting_trips'],['t3'])
        self.assertEqual(verify.failed_checks(status),[])

    def test_every_trip_valid_reports_validation_complete(self):
        trips=[{'tab_id':'t1','display_key':'alpha'},{'tab_id':'t2','display_key':'beta'}]
        flow=flow_stub(trips,valid_ids={'t1','t2'})
        status=verify.collect_runtime_status(
            flow,config={'decisions_db_path':'synthetic-board.sqlite'})
        self.assertTrue(status['schedule_validation_complete'])
        self.assertEqual(status['invalid_trip_count'],0)
        self.assertEqual(status['waiting_trips'],[])
        self.assertEqual(verify.failed_checks(status),[])


class CountsAndDocumentComparisonAreObservationsOnly(unittest.TestCase):
    def test_counts_never_decide_health(self):
        trips=[{'tab_id':'t1','display_key':'alpha'}]
        flow=flow_stub(trips,valid_ids={'t1'})
        status=verify.collect_runtime_status(
            flow,config={'decisions_db_path':'synthetic-board.sqlite'})
        # 어떤 건수여도 판정에 들어가지 않는다.
        self.assertNotIn('input_events',verify.HEALTH_ROUTES)
        for count in (0,1,5328,1676):
            with self.subTest(input_events=count):
                self.assertEqual(verify.failed_checks(dict(status,input_events=count)),[])

    def test_authority_document_mismatch_is_reported_not_failed(self):
        trips=[{'tab_id':'t1','display_key':'alpha'},{'tab_id':'t2','display_key':'beta'}]
        flow=flow_stub(trips,valid_ids={'t1','t2'})
        records=[SimpleNamespace(trip_code='alpha',is_authoritative=True),
                 SimpleNamespace(trip_code='gamma',is_authoritative=True)]
        self.patch_loader(records)
        status=verify.collect_runtime_status(
            flow,config={'decisions_db_path':'synthetic-board.sqlite'},
            authority_path='synthetic-authority.json')
        self.assertFalse(status['authority_matches_board'])
        self.assertEqual(status['authority_trip_codes'],['alpha','gamma'])
        self.assertEqual(status['board_trip_codes'],['alpha','beta'])
        self.assertEqual(status['authority_records'],2)
        self.assertEqual(verify.failed_checks(status),[])

    def patch_loader(self, records):
        import ledger.domain.direct_trip_schedule_authority as module
        original=module.load_document
        module.load_document=lambda path:(records,None)
        self.addCleanup(lambda:setattr(module,'load_document',original))


class RealDefectsStillFail(unittest.TestCase):
    def base(self, **overrides):
        trips=[{'tab_id':'t1','display_key':'alpha'}]
        status=verify.collect_runtime_status(
            flow_stub(trips,valid_ids={'t1'}),
            config={'decisions_db_path':'synthetic-board.sqlite'})
        status.update(overrides)
        return status

    def test_a_different_review_database_fails(self):
        self.assertIn('review_uses_board',
                      verify.failed_checks(self.base(review_uses_board=False)))

    def test_a_broken_database_fails(self):
        self.assertEqual(verify.failed_checks(self.base(integrity='malformed')),
                         ['db_integrity'])

    def test_an_unprotected_route_fails(self):
        cases={'/import':200,'/api/imports':404,'/healthz':500}
        for route,status in cases.items():
            with self.subTest(route=route,status=status):
                http=dict(verify.HEALTH_ROUTES)
                http[route]=status
                self.assertIn('unauthenticated_http_protected',
                              verify.failed_checks(self.base(unauthenticated_http=http)))

    def test_http_protection_is_expected_to_be_reported(self):
        self.assertEqual(verify.HEALTH_ROUTES,
                         {'/healthz':200,'/readyz':200,'/import':401,'/api/imports':401})


class RoutesAreProbedThroughTheInjectedProbe(unittest.TestCase):
    def test_the_probe_supplies_every_status(self):
        trips=[{'tab_id':'t1','display_key':'alpha'}]
        asked=[]
        def probe(route):
            asked.append(route)
            return verify.HEALTH_ROUTES[route]
        status=verify.collect_runtime_status(
            flow_stub(trips,valid_ids={'t1'}),
            config={'decisions_db_path':'synthetic-board.sqlite'},
            routes=tuple(verify.HEALTH_ROUTES),probe=probe)
        self.assertEqual(sorted(asked),sorted(verify.HEALTH_ROUTES))
        self.assertEqual(status['unauthenticated_http'],verify.HEALTH_ROUTES)
        self.assertEqual(verify.failed_checks(status),[])

    def test_no_routes_means_nothing_is_probed_and_nothing_fails(self):
        trips=[{'tab_id':'t1','display_key':'alpha'}]
        status=verify.collect_runtime_status(
            flow_stub(trips,valid_ids={'t1'}),
            config={'decisions_db_path':'synthetic-board.sqlite'},routes=())
        self.assertEqual(status['unauthenticated_http'],{})
        self.assertEqual(verify.failed_checks(status),[])


class TripCountingIsSharedByBothPaths(unittest.TestCase):
    def test_waiting_and_verified_add_up_to_every_trip(self):
        trips=[{'tab_id':'t%d'%n,'display_key':'k%d'%n} for n in range(40)]
        valid=verify.validated_trip_ids(flow_stub(trips,valid_ids={'t%d'%n for n in range(37)}),trips)
        verified,waiting=verify.count_valid_trips(valid)
        self.assertEqual((verified,waiting),(37,3))
        self.assertEqual(verified+waiting,len(trips))

    def test_one_aggregate_call_does_not_recheck_the_same_trip(self):
        trips=[{'tab_id':'t1','display_key':'alpha'},{'tab_id':'t2','display_key':'beta'}]
        calls=[]
        flow=flow_stub(trips,valid_ids={'t1'})
        flow.trip_valid=lambda tab_id:(calls.append(tab_id) or tab_id=='t1')
        status=verify.collect_runtime_status(
            flow,config={'decisions_db_path':'synthetic-board.sqlite'})
        self.assertEqual(sorted(calls),['t1','t2'])
        self.assertEqual(status['verified_trip_count'],1)
        self.assertEqual(status['invalid_trip_count'],1)
        self.assertEqual(status['waiting_trips'],['t2'])

    def test_a_later_call_revalidates_from_the_source_again(self):
        trips=[{'tab_id':'t1','display_key':'alpha'}]
        flow=flow_stub(trips,valid_ids=set())
        flow.trip_valid=lambda tab_id:False
        first=verify.collect_runtime_status(
            flow,config={'decisions_db_path':'synthetic-board.sqlite'})
        self.assertEqual(first['invalid_trip_count'],1)
        flow.trip_valid=lambda tab_id:True
        second=verify.collect_runtime_status(
            flow,config={'decisions_db_path':'synthetic-board.sqlite'})
        self.assertEqual(second['invalid_trip_count'],0)
        self.assertTrue(second['schedule_validation_complete'])


class PartialObservationIsNotAFullVerification(unittest.TestCase):
    def collect(self, routes, authority='', **kwargs):
        trips=[{'tab_id':'t1','display_key':'alpha'}]
        return verify.collect_runtime_status(
            flow_stub(trips,valid_ids={'t1'}),
            config={'decisions_db_path':'synthetic-board.sqlite'},
            routes=routes,probe=lambda route:verify.HEALTH_ROUTES.get(route,0),
            authority_path=authority,**kwargs)

    def test_no_routes_is_not_complete_and_has_no_failed_check(self):
        status=self.collect(())
        self.assertFalse(status['runtime_verification_complete'])
        self.assertEqual(status['probed_routes'],[])
        self.assertEqual(status['unauthenticated_http'],{})
        self.assertEqual(verify.failed_checks(status),[])

    def test_some_routes_is_not_complete(self):
        status=self.collect(('/healthz','/readyz'))
        self.assertEqual(status['probed_routes'],['/healthz','/readyz'])
        self.assertFalse(status['runtime_verification_complete'])
        self.assertEqual(verify.failed_checks(status),[])

    def test_every_route_without_the_authority_document_is_not_complete(self):
        status=self.collect(tuple(verify.HEALTH_ROUTES))
        self.assertEqual(status['probed_routes'],sorted(verify.HEALTH_ROUTES))
        self.assertFalse(status['runtime_verification_complete'])
        self.assertEqual(verify.failed_checks(status),[])

    def test_all_routes_and_the_document_are_complete(self):
        self.patch_loader([SimpleNamespace(trip_code='alpha',is_authoritative=True)])
        status=self.collect(tuple(verify.HEALTH_ROUTES),authority='synthetic-authority.json')
        self.assertTrue(status['runtime_verification_complete'])
        self.assertEqual(verify.failed_checks(status),[])

    def patch_loader(self, records):
        import ledger.domain.direct_trip_schedule_authority as module
        original=module.load_document
        module.load_document=lambda path:(records,None)
        self.addCleanup(lambda:setattr(module,'load_document',original))

    def test_a_route_the_probe_could_not_read_is_incomplete(self):
        status=self.collect(tuple(verify.HEALTH_ROUTES)+('/export',))
        self.assertFalse(status['runtime_verification_complete'])
        self.assertIn('unauthenticated_http_protected',verify.failed_checks(status))


class TheCliFailsLoudly(unittest.TestCase):
    def test_a_healthy_result_exits_zero(self):
        self.assertEqual(verify.cli_exit_code({'ok':True}),0)

    def test_a_failed_result_exits_non_zero(self):
        for failed in (['db_integrity'],['runtime_verification_incomplete'],
                       ['review_uses_board','unauthenticated_http_protected']):
            with self.subTest(failed=failed):
                self.assertEqual(verify.cli_exit_code({'ok':False,'failed_checks':failed}),1)

    def test_an_incomplete_verification_is_named_as_a_failure(self):
        trips=[{'tab_id':'t1','display_key':'alpha'}]
        status=verify.collect_runtime_status(
            flow_stub(trips,valid_ids={'t1'}),
            config={'decisions_db_path':'synthetic-board.sqlite'},
            routes=('/healthz',),probe=lambda route:200)
        status['failed_checks']=verify.failed_checks(status)
        if not status['runtime_verification_complete']:
            status['failed_checks'].append('runtime_verification_incomplete')
        status['ok']=not status['failed_checks']
        self.assertIn('runtime_verification_incomplete',status['failed_checks'])
        self.assertEqual(verify.cli_exit_code(status),1)


if __name__=='__main__':
    unittest.main()