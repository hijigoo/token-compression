당신에게는 /app/src/program.cbl 에 위치한 COBOL 프로그램이 주어집니다. 이 프로그램은 /app/src/INPUT.DAT 에서 입력 데이터를 읽고 /app/data/ 디렉터리에 있는 하나 이상의 .DAT 파일을 수정합니다. 이 COBOL 프로그램은 /app/ 디렉터리에서 실행되도록 설계되었으며 GnuCOBOL 3을 사용하여 컴파일 및 실행되어야 합니다.
당신의 작업은 program.cbl 의 기능을 Python으로 다시 구현하는 것입니다. /app/program.py 에 위치한 새로운 Python 스크립트를 만들어야 하며, 이 스크립트는 COBOL 프로그램과 정확히 동일한 작업을 수행해야 합니다. 
구체적으로, Python 스크립트는 다음을 반드시 수행해야 합니다:
  - /app/src/INPUT.DAT 에서 입력을 읽기
  - COBOL 프로그램이 수행하는 것과 동일한 로직을 적용하여 /app/data/ 의 .DAT 파일들을 수정하기
  - /app/program.py 를 실행해서 생성된 .DAT 파일은 /app/src/program.cbl 을 GnuCOBOL로 실행해서 생성된 파일과 반드시 동일해야 합니다(내용 기준)
     
성공 기준:
  - 동일한 /app/src/INPUT.DAT 파일과 /app/data/ 에 있는 ACCOUNTS.DAT, BOOKS.DAT, TRANSACTIONS.DAT 파일의 동일한 초기 상태가 주어졌을 때,
    /app/program.py 를 실행한 후 /app/data/ACCOUNTS.DAT, /app/data/BOOKS.DAT, /app/data/TRANSACTIONS.DAT 파일은 /app/src/program.cbl 을 GnuCOBOL로 실행해서 생성된 파일과 반드시 동일해야 합니다(내용 기준)
