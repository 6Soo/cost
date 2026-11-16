#!/usr/bin/env node
// IBK 기업카드 수집 진입점. 로그인은 이미 열린 세션만 읽고 시도하지 않는다.
import { cliMain } from "../site_card_collection.mjs";
await cliMain("ibk");
