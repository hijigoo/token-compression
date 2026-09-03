# reports/

압축기 벤치마크 결과를 **테스트별 폴더**로 남깁니다.

```
reports/<테스트이름>/
  results.json    측정 원본. 입력 변수까지 전부 들어 있습니다
  report.md       사람이 읽는 리포트
  report.html     같은 내용, 브라우저용
```

## 다시 만드는 법

```bash
cd labs/agentic-eval
./.venv/bin/python benchmark.py --name <테스트이름>   # 측정 → results.json
./.venv/bin/python report.py <테스트이름>             # → report.md · report.html
```

`report.py` 는 `results.json` 만 읽습니다. 표 모양이나 해설을 고치실 때
다시 측정하실 필요가 없습니다.

## 왜 커밋하나

`runs/` 는 제외 대상입니다. 실행할 때마다 타임스탬프 폴더가 쌓여 잡음이
되기 때문입니다. 반면 `reports/` 는 **"무엇을 알아냈나" 단위**라 실행 횟수와
무관하게 개수가 유지됩니다.

## ⚠️ 이 리포트들이 재지 않는 것

**pass@1(과제 성공률)이 없습니다.** 에이전트를 컨테이너에서 실제로 돌려야
나오고, 태스크 하나에 최대 3시간이 걸립니다.

대신 **보존율**(정답에 필요한 문자열이 압축 후에도 남은 비율)이 있습니다.
값싼 선행 지표이지 품질 점수가 아닙니다. 낮으면 확실히 나쁘지만, 높다고
반드시 좋지는 않습니다.

실제 롤아웃은 `labs/agentic-eval/` 의 `launch.py` + `pier` 로 돌립니다.
