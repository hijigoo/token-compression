회사에서 내부 개발 서버용 self-signed TLS 인증서가 필요합니다. 다음 요구사항에 따라 OpenSSL을 사용하여 self-signed 인증서를 생성하세요:

1. 모든 파일을 저장할 디렉터리를 `/app/ssl/` 에 생성하세요

2. 2048비트 RSA private key를 생성하세요:
   - `/app/ssl/server.key` 로 저장하세요
   - key 파일에 올바른 권한(600)을 설정하세요

3. 다음 세부 정보로 self-signed 인증서를 생성하세요:
   - 365일(1년) 동안 유효해야 합니다
   - Organization Name: "DevOps Team"
   - Common Name: "dev-internal.company.local"
   - `/app/ssl/server.crt` 로 저장하세요

4. private key와 인증서를 모두 포함하는 결합된 PEM 파일을 생성하세요:
   - `/app/ssl/server.pem` 로 저장하세요

5. 인증서 세부 정보를 검증하세요:
   - 다음 내용을 포함하는 `/app/ssl/verification.txt` 라는 파일을 생성하세요:
     - 인증서의 subject
     - 인증서의 유효 기간 날짜(YYYY-MM-DD 형식 또는 timezone이 선택적으로 포함된 OpenSSL 형식)
     - 인증서의 SHA-256 fingerprint

6. `/app/check_cert.py` 에 간단한 Python 스크립트를 작성하세요. 이 스크립트는 다음을 수행해야 합니다:
   - 인증서가 존재하고 로드할 수 있는지 검증합니다
   - Common Name과 YYYY-MM-DD 형식의 만료일을 포함한 인증서 세부 정보를 출력합니다
   - 모든 검사가 통과하면 "Certificate verification successful" 을 출력합니다

작업을 완료하기 위해 OpenSSL 명령어를 사용하고, 모든 파일이 올바른 형식과 권한을 갖도록 하세요.
