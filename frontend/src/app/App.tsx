import { useState, type ReactNode } from "react";
import type { AppRole, AppShellProps, AppTrip } from "./AppShell";
import { AppShell } from "./AppShell";
import {
  ActionButton,
  Amount,
  Checkbox,
  DataTable,
  Drawer,
  EmptyState,
  FormField,
  InlineNotice,
  Input,
  JobStatus,
  Loading,
  RadioGroup,
  Select,
  Switch,
  Tabs,
} from "../components";

export type AppProps = {
  role?: AppRole;
  trips?: AppTrip[];
  path?: string;
  currentTripId?: AppShellProps["currentTripId"];
  onTripSelect?: AppShellProps["onTripSelect"];
  children?: ReactNode;
};

export function ComponentGallery() {
  const [selectedTab, setSelectedTab] = useState("controls");
  const [checked, setChecked] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [radio, setRadio] = useState("first");
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="cost-gallery">
      <header className="cost-gallery-header">
        <p className="cost-eyebrow">UI 기반 구성요소</p>
        <h1>Plush UI 갤러리</h1>
        <p className="cost-gallery-intro">실제 화면에 연결하기 전 공용 입력·선택·상태 컴포넌트를 확인합니다. 이 페이지에는 업무 데이터가 없습니다.</p>
      </header>

      <Tabs
        ariaLabel="갤러리 보기"
        items={[{ id: "controls", label: "조작" }, { id: "states", label: "상태" }]}
        value={selectedTab}
        onChange={setSelectedTab}
      />

      {selectedTab === "controls" ? (
        <div className="cost-gallery-grid">
          <section className="cost-gallery-card">
            <h2>버튼</h2>
            <div className="cost-gallery-row">
              <ActionButton>주요 동작</ActionButton>
              <ActionButton variant="secondary">보조 동작</ActionButton>
              <ActionButton variant="ghost">텍스트 동작</ActionButton>
            </div>
          </section>

          <section className="cost-gallery-card">
            <h2>입력과 선택</h2>
            <FormField id="gallery-search" label="검색 예시" hint="가시 라벨과 보조 설명 연결을 확인합니다.">
              <Input placeholder="내용 검색" />
            </FormField>
            <FormField id="gallery-category" label="선택 예시">
              <Select defaultValue="">
                <option value="" disabled>항목 선택</option>
                <option value="one">첫 번째 항목</option>
                <option value="two">두 번째 항목</option>
              </Select>
            </FormField>
            <Checkbox label="확인 예시" description="전체 문구가 선택 영역입니다." checked={checked} onCheckedChange={(value) => setChecked(value === true)} />
            <Switch label="스위치 예시" description="실제 설정을 저장하지 않습니다." checked={enabled} onCheckedChange={setEnabled} />
            <RadioGroup
              label="라디오 예시"
              name="gallery-radio"
              value={radio}
              onChange={setRadio}
              options={[{ value: "first", label: "첫 번째 선택" }, { value: "second", label: "두 번째 선택" }]}
            />
          </section>

          <section className="cost-gallery-card">
            <h2>표와 금액</h2>
            <p className="cost-help-text">합성 금액 · 정밀도 확인</p>
            <Amount value="12345678901234567890" />
            <DataTable
              caption="빈 표 예시"
              columns={[{ key: "name", header: "항목", cell: () => "" }]}
              rows={[]}
              getRowKey={() => "empty"}
              emptyState={<EmptyState title="표 행 없음" description="빈 상태의 표현을 확인합니다." />}
            />
          </section>

          <section className="cost-gallery-card">
            <h2>상세 서랍</h2>
            <p className="cost-help-text">Escape와 닫기 조작을 확인합니다.</p>
            <ActionButton variant="secondary" onClick={() => setDrawerOpen(true)}>서랍 열기</ActionButton>
            <Drawer open={drawerOpen} title="상세 보기 예시" description="합성 내용입니다." onOpenChange={setDrawerOpen}>
              <p>여기에 실제 선택한 항목의 상세 내용이 들어갑니다.</p>
            </Drawer>
          </section>
        </div>
      ) : (
        <div className="cost-gallery-grid">
          <section className="cost-gallery-card">
            <h2>상태 알림</h2>
            <InlineNotice tone="info" title="정보 상태">추가 정보가 이 영역에 표시됩니다.</InlineNotice>
            <InlineNotice tone="success" title="완료 상태">성공 메시지는 색상 외에 텍스트로 전달됩니다.</InlineNotice>
            <InlineNotice tone="warning" title="주의 상태">사용자가 다음 행동을 결정할 수 있도록 이유를 표시합니다.</InlineNotice>
            <InlineNotice tone="error" title="오류 상태">실패 원인과 복구 방법이 가까이 표시됩니다.</InlineNotice>
          </section>
          <section className="cost-gallery-card">
            <h2>작업 상태</h2>
            <JobStatus state="unknown" message="실제 서버 상태가 연결되면 이 위치에 표시됩니다." />
            <Loading label="로딩 표현" />
          </section>
          <section className="cost-gallery-card">
            <h2>오류 있는 입력</h2>
            <FormField id="gallery-error" label="필수 항목" required error="입력값을 확인하세요.">
              <Input invalid aria-invalid="true" />
            </FormField>
          </section>
        </div>
      )}
    </div>
  );
}

export function App({ role = "owner", trips = [], path, currentTripId, onTripSelect, children }: AppProps) {
  const currentPath = path ?? (typeof window === "undefined" ? "/" : window.location.pathname);
  return (
    <AppShell role={role} trips={trips} path={currentPath} currentTripId={currentTripId} onTripSelect={onTripSelect}>
      {children ?? <ComponentGallery />}
    </AppShell>
  );
}

export default App;
