#!/usr/bin/env node
// 하나 기업카드 수집 진입점. 사이트 화면 계약은 라이브 확인 전까지 비활성이다.
import { runProviderCollection } from "../site_card_collection.mjs";
runProviderCollection("hana").then((r) => { console.log(JSON.stringify(r)); if (r.status !== "ok") process.exitCode = 2; });
