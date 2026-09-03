로그 파일에서 IPv4 주소를 포함하는 줄에 나타나는 `YYYY-MM-DD` 형식의 날짜와 일치하는 regex 표현식을 작성하세요.
한 줄에 날짜가 여러 개 있으면, regex는 그 줄의 마지막 날짜와만 일치해야 합니다.
윤년과 평년을 구분하지 않고, 모든 연도에서 2월은 최대 29일까지 있다고 가정하세요.
IPv4 주소는 각 옥텟에 선행 0이 없는 일반적인 10진 표기법을 사용합니다.

참고: 로그에 날짜나 IPv4 주소와 비슷해 보이지만 실제로는 아닌 텍스트가 있을 수 있다는 점에 주의하세요(예: user 1134-12-1234). 
잘못된 매치를 피하기 위해, 올바른 날짜와 IPv4 주소의 바로 앞이나 뒤에 영숫자 문자가 오지 않도록 보장하세요.

regex를 /app/regex.txt에 저장하세요.
regex는 파일에서 읽혀 Python의 `re.findall`에 `re.MULTILINE` 플래그와 함께 적용되어 로그 파일 내용에 사용됩니다.
예시 Python 사용법:
```
import re

with open("/app/regex.txt") as f:
    pattern = f.read().strip()

matches = re.findall(pattern, log_text, re.MULTILINE)
```
