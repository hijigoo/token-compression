여러 로그 파일이 /app/logs에 저장되어 있습니다. 각 로그 파일 이름은 YYYY-MM-DD_<source>.log 패턴(예: 2025-08-10_db.log)을 따르며, 이는 로그의 날짜와 그 소스를 나타냅니다. 각 로그 줄에는 severity level이 포함된 이벤트가 들어 있습니다. 당신의 작업은 모든 로그를 분석하고 다음 날짜 범위 내에서 각 severity가 몇 번 나타나는지 세는 것입니다:
Today (현재 날짜)
Last 7 days (오늘 포함)
Last 30 days (오늘 포함)
Current month to date (현재 월의 1일로부터 오늘까지, 오늘 포함)
Total (날짜와 관계없이 모든 로그 파일을 합친 전체)

집계할 severity level은 정확히 다음과 같습니다: ERROR, WARNING, and INFO.
다음 구조(헤더 포함)로 CSV 파일 /app/summary.csv를 작성하세요:
period,severity,count
today,ERROR,<count>
today,WARNING,<count>
today,INFO,<count>
last_7_days,ERROR,<count>
last_7_days,WARNING,<count>
last_7_days,INFO,<count>
last_30_days,ERROR,<count>
last_30_days,WARNING,<count>
last_30_days,INFO,<count>
month_to_date,ERROR,<count>
month_to_date,WARNING,<count>
month_to_date,INFO,<count>
total,ERROR,<count>
total,WARNING,<count>
total,INFO,<count>

각 행은 해당 날짜 범위에 대해 각 severity의 총 개수를 보고해야 합니다.
현재 날짜는 2025-08-12입니다. 모든 계산의 기준 날짜로 이것을 사용하세요.
로그 파일명은 항상 YYYY-MM-DD_<source>.log 패턴을 따른다고 가정해도 됩니다.
