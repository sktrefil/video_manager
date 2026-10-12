# video_manager

공유 끝·시작 이미지를 사용하는 생성 영상의 연결부 분석과 후반 시간 압축 도구입니다.
현재 구현 범위는 **A1~A4 연결부 진단 + B1 시간 압축 + B2 내부 움직임 검토 + C JSON 작업 + D 데스크톱 UI**입니다.
실제 영상의 자연스러움과 Windows 배포판은 별도 검증 대상입니다.

## 개발 환경

Python 3.11 이상, `ffmpeg`, `ffprobe`, FFmpeg의 `libx264` 인코더가 필요합니다.
검증 환경: Linux, Python 3.12.14, FFmpeg 7.1.5. 프레임 진단 표시에 Pillow 11.1.0, 움직임 측정에 NumPy 2.2.3·OpenCV headless 4.11.0.86을 사용합니다.
빌드 도구와 런타임 패키지는 정확한 버전으로 고정하며 테스트는 표준 라이브러리 `unittest`를 사용합니다.

기존 체크아웃에서 실행합니다. 각 클라우드 작업은 격리되어 있으므로 별도 Git worktree가 필요하지 않습니다.

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
.venv/bin/video-manager --help
.venv/bin/video-manager doctor
.venv/bin/python -m unittest discover -s tests/unit -v
```

## VS Code에서 시작하기

저장소를 복제하고 폴더를 VS Code에서 엽니다. Python 3.12를 권장합니다.

```bash
git clone https://github.com/sktrefil/video_manager.git
cd video_manager
code .
```

Windows PowerShell에서는 가상환경 활성화 없이 다음 명령으로 설치·실행할 수 있습니다.
FFmpeg와 ffprobe를 먼저 설치하고 PATH에 등록하세요.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[gui]"
.\.venv\Scripts\video-manager.exe doctor
.\.venv\Scripts\video-manager.exe gui
```

VS Code의 `Python: Select Interpreter`에서 `.venv`를 선택합니다.
Linux/macOS에서는 위 개발 환경 설치 후 `requirements-ui.txt`를 설치하고
`.venv/bin/video-manager gui`를 실행합니다. GUI에는 실제 데스크톱 세션이 필요합니다.
Windows 실행·배포는 아직 검증하지 않았습니다.

검토 영상 ZIP은 [review_assets/video_review_11s_8s.zip](review_assets/video_review_11s_8s.zip)에 있습니다.
원본 입력 영상은 저장소에 포함하지 않습니다. JSON 예제의 입력·출력 경로를 자신의 환경에 맞게 수정하세요.

## 작업 경로 준비

```bash
.venv/bin/video-manager prepare 'inputs/클립 1.mp4' 'inputs/클립 2.mp4' --output outputs/job_001
```

입력 순서를 보존하며 최소 2개의 읽을 수 있는 비어 있지 않은 일반 파일을 요구합니다.
A1의 `prepare`는 **파일 경로만 검사**합니다. 실제 미디어 유효성 검사는 A2에서 추가합니다.
도구 진단이 통과하면 새로운 작업 디렉터리를 생성하고 `results/preparation.json`에 입력 순서와 도구 정보를 기록합니다.
기존 출력 경로는 빈 디렉터리여도 거절합니다. 재실행할 때 새 이름을 지정하세요.
원본은 읽기 전용으로 취급하며 외부 명령은 셸 없이 인수 배열로 실행합니다.

작업 중에는 작업 디렉터리 안의 독립된 `.work-*` 경로를 사용하며,
성공 시에만 `results`로 이름을 변경합니다. `status.json`으로 상태를 확인합니다.
실패·취소 시 중간 파일과 진단 정보를 보존하며 성공 결과로 표시하지 않습니다.

종료 코드: `0` 성공, `1` I/O·처리 실패, `2` 입력·사용법 오류,
`3` 필수 도구 누락·실행 실패, `130` 사용자 취소.

설계·단계별 완료 기준은 [설계서](docs/DESIGN.md)와 [작업지시서](docs/WORK_INSTRUCTIONS.md)를 참고하세요.

## A2: 보정 없는 기준 연결과 진단

```bash
.venv/bin/video-manager baseline 'inputs/클립 1.mp4' 'inputs/클립 2.mp4' 'inputs/클립 3.mp4' --output outputs/baseline_001
.venv/bin/python tests/fixtures/synthetic.py outputs/synthetic_001
.venv/bin/python -m unittest discover -s tests/integration -v
```

`baseline`은 입력 영상의 실제 표시 프레임 PTS를 조사하고 순서대로 연결합니다.
첫 클립의 평균 FPS(없으면 ffprobe의 기준 FPS)로 CFR 출력을 만들며, 첫 클립의
표시 해상도를 짝수·정방형 픽셀로 정규화합니다. 다른 화면 비율은 검은 패딩으로 맞춥니다.
가장 가까운 원본 PTS의 프레임을 선택하고 같은 거리이면 이전 프레임을 선택합니다.
각 클립의 첫·끝 프레임을 보존합니다. FPS 변환 때문에 프레임이 반복·제외될 수 있으며
프레임 반올림에 따른 길이 차이를 보고합니다. 이 단계에는 연결부 보정·시간 압축이 없습니다.
**오디오는 출력에서 제외**하며 원본의 오디오 존재 여부는 보고합니다.

`results/` 산출물:

- `baseline.mp4`: 진단 글자가 없는 기준 영상.
- `baseline_diagnostic.mp4`: 클립 ID·0부터 시작하는 원본 표시 프레임 번호·정규화 원본 시간·출력 프레임/시간 표시.
- `baseline_boundary_01.mp4` 등: 경계 앞뒤 기본 0.5초의 진단 구간. 경계 위치는 보고서에 기록.
- `report.json`: 입력 해시·도구 버전·PTS/time base·VFR·오디오·출력→원본 매핑·프레임 수·실측 길이.

시간 표시의 원본 시간은 `(프레임 PTS - 첫 표시 프레임 PTS) × time base`이며,
원래 비영 시작 PTS도 보고서에 보존합니다. CFR 출력 시간과 혼용하지 않습니다.
영상 전체 프레임 이미지를 쌓지 않고 순차 디코딩·인코딩합니다. 프레임 메타데이터와
매핑 목록은 메모리에 보관하므로 매우 긴 영상은 아직 성능 검증 대상이 아닙니다.
실제 클립의 시각 품질은 합성 테스트 통과와 별도로 검증해야 합니다.

## A3: 연결부 측정과 보정 후보

```bash
.venv/bin/video-manager boundaries 'inputs/클립 1.mp4' 'inputs/클립 2.mp4' 'inputs/클립 3.mp4' \
  --output outputs/candidate_001 --window 0.8 --strength 0.7 --local-speed --remove-duplicates
# 2번 클립에 닿는 양쪽 경계 보정을 제외하거나, 특정 경계만 제외:
.venv/bin/video-manager boundaries 'inputs/클립 1.mp4' 'inputs/클립 2.mp4' 'inputs/클립 3.mp4' \
  --output outputs/candidate_002 --local-speed --remove-duplicates --disable-clip 2 --disable-boundary 1
```

번호는 입력 순서에 따른 1부터 시작하는 값입니다. `--disable-clip`과
`--disable-boundary`는 여러 번 지정할 수 있습니다. 클립 제외는 그 클립에 접한
양쪽 경계의 속도 조절·중복 제거를 모두 금지하며, 경계 제외는 해당 경계만 금지합니다.
클립 자체는 출력에서 삭제되지 않습니다. **출력 규격의 FPS·해상도 정규화는 제외 대상이 아닙니다.**
명시적 비활성화가 자동 후보보다 우선합니다. 실행 결과에는 설정과 실제 적용·제외 사유를 기록합니다.

기본은 분석과 원본 그대로인 후보 출력입니다. `--local-speed`와 `--remove-duplicates`는
각각 독립적인 명시적 요청이며 자동 활성화되지 않습니다.
160×96 분석 영상의 Farneback optical flow로 경계 양쪽의 이동 속도·방향·신뢰도,
프레임 차이·정지 후보·밝기 차이를 측정합니다. 각 창은 최대 16프레임을 샘플링합니다.
신뢰도는 활성 움직임 영역·영상 텍스처·방향 일관성을 조합한 휴리스틱입니다.
양쪽 신뢰도 중 하나가 0.35 미만이거나 정적 구간이면 속도를 조절하지 않습니다.
방향 내적이 -0.25보다 작으면 방향 충돌로 표시하고 속도 조절 후보에서 제외합니다.
형태 변형·가림·의도된 정지를 자동 판별하거나 복구하지 않습니다.

중복 제거는 끝·시작 프레임이 저해상도 RGB MAE ≤ 3, RMSE ≤ 8인 경우에만
다음 클립의 원본 0번 프레임과 그 CFR 반복분을 제거합니다. 앞 클립의 끝 프레임을
공유 이미지의 대표로 유지하고 보고서에 기록합니다. 뒤따르는 원본 프레임이 정지
상태라도 삭제하지 않습니다. 한 프레임뿐인 클립을 없애지 않습니다.
**유사도는 동일 이미지의 증명이 아니므로 출력은 검토할 후보입니다.** 제거한 프레임 수만큼
후보 길이가 줄며, 이 단계에서는 전체 목표 시간 재배분을 하지 않습니다.

### 국소 시간 곡선

창 폭 `--window`는 0초 초과·2초 이하, 강도 `--strength`는 0~1입니다.
각 클립에서 창을 첫·마지막 표시 PTS 간격의 절반 이하로 제한하여 양쪽 창이 겹치지 않게 합니다.
원본 이동 속도가 `vL`, `vR`이면 목표 후보 속도는 `sqrt(vL*vR)`이며,
각 창의 계수는 `a = strength * clamp(target/v - 1, -0.8, 0.8)`입니다.

창 내부의 정규화된 출력 위치를 `u`(0~1)라 할 때 원본 위치는 다음 곡선으로 정합니다.

- 클립 시작 창: `q(u) = u + a*u*(1-u)^2`
- 클립 끝 창: `q(u) = u + a*u^2*(u-1)`

두 식은 첫·끝 대응을 고정하고 도함수가 양수여서 시간 역행이 없습니다.
안쪽 접합점의 배속은 1, 경계의 배속은 `1+a`입니다. 빠른 쪽은 경계에서 느려지고,
느린 쪽은 빨라집니다. 전역 길이는 유지하며 창 안에서 시간을 재분배합니다.
원본 PTS로 양자화하므로 낮은 FPS·작은 강도에서는 선택 프레임이 바뀌지 않을 수 있습니다.
보고서의 실제 프레임 매핑과 `positional_schedule_changes`로 효과를 확인하세요.

### 비교 산출물

`results/`에 `baseline.mp4`, `corrected.mp4`, 각각의 `_diagnostic.mp4`,
경계 구간 영상, `comparison_boundary_01.mp4` 등과 `report.json`을 저장합니다.
비교 영상은 같은 경계를 상대 시간 0에 놓고 같은 FPS·상대 시간으로 재생합니다.
추가 배속을 적용하지 않습니다. 범위 밖은 검은 화면과 `OUT OF RANGE`로 표시하며
마지막 프레임으로 채우지 않습니다. 각 화면의 원본·출력 위치는 서로 독립적으로 표시합니다.
보고서는 비교 프레임별 양쪽 원본 매핑, 실제 출력에서 다시 측정한 움직임과 길이 변화도 포함합니다.
수치 개선은 품질 통과를 의미하지 않습니다. 실제 정상 속도 비교와 사용자 확인이 필요합니다.

## A4: 반복 가능한 합성 검토 패키지

```bash
.venv/bin/python tests/fixtures/run_a4_demo.py outputs/a4-demo
```

이미 있는 출력 경로는 거절합니다. 다시 실행할 때는 `outputs/a4-demo-002`처럼 새 경로를 지정하세요.
두 개의 4클립 시퀀스로 동일 속도·공유 끝 이미지, 빠름→느림, 방향 반전, 정지 유지,
끝 이미지의 작은 차이를 생성합니다. 보정 꺼짐·켜짐과 2번 클립 제외 사례를 실행하며,
모든 출력 디코딩·프레임 수·원본 해시·동기 비교·제외 우선순위를 검사합니다.
`manifest.json`에 정확한 명령 인수와 입력·출력 식별 정보가 있고 `REVIEW.md`에 비교 위치가 있습니다.
생성 영상은 `outputs/`에만 저장되며 Git 추적에서 제외합니다.

실제 샘플을 받으면 다음처럼 **새 출력 경로**로 실행합니다.

```bash
.venv/bin/video-manager boundaries 'inputs/실제 1.mp4' 'inputs/실제 2.mp4' 'inputs/실제 3.mp4' \
  --output outputs/real-review-001 --window 0.5 --strength 0.3 --local-speed --remove-duplicates
```

초기값은 품질 보장이 아닙니다. `baseline.mp4`·`corrected.mp4`와 경계별 비교를 정상 속도로 보고
클립 ID·원본 프레임·출력 시간으로 결함을 기록합니다. 인물·배경 형태 변화, 가림, 의도된 정지,
복잡한 카메라 움직임에는 국소 배속만으로 해결되지 않을 수 있습니다.
**합성 기능 검증과 실제 품질 확인은 별개입니다.** 사용자의 후속 지시에 따라 B1→B2→C→D 코드를 먼저 순차 구현하며, 실제 시각 품질은 별도로 미확인 상태를 유지합니다.

## B1: 초반 보호와 목표 시간 압축

```bash
.venv/bin/video-manager retime 'inputs/클립 1.mp4' 'inputs/클립 2.mp4' 'inputs/클립 3.mp4' \
  --targets 3 4 4 --protect 1 1 1 --max-speed 12 --ramp 0.5 --output outputs/retime-001
```

`--targets`, `--protect`, `--max-speed`, `--ramp`는 클립별 값 또는 모든 클립에 쓸 단일 값을 받습니다.
초반 보호 기본값은 **1초**이며 의미 분석 결과가 아닙니다. 배속 상한 기본값은 12배,
가속 전환 폭 기본값은 출력 시간 기준 0.5초입니다. 보호 시간이 원본 길이를 넘거나,
압축 시 보호 구간이 마지막 출력 프레임까지 이어지거나, 전환 폭이 남은 구간보다 길거나,
필요 배속이 상한을 넘으면 거절합니다. 설정을 몰래 완화하지 않습니다.
원본과 목표 길이가 한 출력 프레임 이내이면 시간 압축을 생략하고 출력 규격만 정규화합니다.
원본보다 한 프레임 이상 긴 목표로 늘리기는 지원하지 않습니다.

전체 목표 합계×FPS의 프레임 수를 먼저 반올림하고, 각 클립에 가장 큰 소수 잔여부터
배분합니다. 개별·전체 길이 오차는 한 출력 프레임 이내로 검사합니다.
마지막 표시 프레임의 시간과 컨테이너 길이는 구분하며, 첫·마지막 원본 표시 프레임을
해당 클립의 첫·마지막 출력 프레임에 대응시킵니다.

보호 시간 `P` 이후 전환 폭 `R` 동안 `u=(t-P)/R`에 대해
`v(t)=1+(peak-1)*(3u²-2u³)`로 가속하고 이후 `peak`를 유지합니다.
이 속도를 적분한 원본 시간 매핑이 마지막 표시 프레임에 정확히 도달하도록 `peak`를 계산합니다.
속도는 보호 구간 경계에서 1배속으로 연속 연결됩니다. **배속 상한은 연속 시간 곡선에 대한 제한**이며,
원본 프레임을 선택하는 양자화 이후의 이산 프레임 건너뛰기 비율과는 다릅니다.
보간으로 새 프레임을 만들거나 마지막에 긴 정지 구간을 붙이지 않습니다.

`--local-speed`·`--window`·`--strength`·제외 옵션은 A3와 같습니다.
원본 좌표의 경계 시간 곡선을 B1 매핑에 합성하되 초반 보호와 겹치는 쪽은 제외합니다.
예를 들어 보호 1초이면 다음 클립 시작 쪽 조절은 제외하고 이전 클립 끝 쪽은 안전하면 적용합니다.
합성 도함수의 보수적 배속 상한도 검사하고 충돌 사유를 기록합니다.
보정 제외 클립에 원본과 한 프레임 이상 다른 목표를 요구하면 오류입니다.
B1의 `--remove-duplicates`는 고정 프레임 예산·보호 구간·끝 이미지 조건을 우선하여
현재 **제거 보류**로 보고합니다. 프레임을 삭제한 뒤 정지 프레임으로 메우지 않습니다.

결과 디렉터리에는 다음을 저장합니다.

- `baseline.mp4`: 원본 길이의 연결 기준본.
- `corrected.mp4`: 목표 시간으로 압축한 제작 후보와 `_diagnostic.mp4` 위치 표시본.
- `clip_01.mp4` 등: 클립별 목표 길이 출력과 해당 진단본.
- 경계별 동기 비교 영상과 `report.json`.

보고서 `timeline`에 요청 시간·배분 프레임·최종 배치·실측 길이·오차·보호·속도 곡선을,
`timeline_validation`에 전체 길이·디코딩 프레임 수·연속 PTS 검사 결과를 기록합니다.
출력 오디오는 제외하며 `--audio-mode mute`만 지원합니다. 실제 클립 제작은 후속 B2·C·D 코드 검증 후 진행합니다.

## B2: 클립 내부 의심 구간과 선택 보정

```bash
.venv/bin/video-manager inspect-motion 'inputs/클립 1.mp4' 'inputs/클립 2.mp4' --output outputs/inspect-001
.venv/bin/video-manager retime 'inputs/클립 1.mp4' 'inputs/클립 2.mp4' --targets 4 4 \
  --motion-report outputs/inspect-001/results/motion_report.json \
  --select-region region_ID_FROM_REPORT --output outputs/selected-001
```

`region_ID_FROM_REPORT`는 보고서의 실제 ID로 바꿉니다. `--motion-report`, `--select-region`,
`--exclude-region`을 반복할 수 있습니다. **기본 선택은 없으며**, 분석·미리보기 생성 자체는
최종 결과에 적용하지 않습니다. 같은 ID를 선택·제외하면 제외가 우선입니다.
선택하지 않은 구간은 B1 시간 압축 외의 내부 조절을 받지 않습니다.

검사는 160×96 순차 영상의 프레임 차이와 optical flow를 사용합니다.
기본적으로 차이가 작은 상태가 0.2초 이상이면 반복·정지 의심 구간으로,
앞뒤 0.4초 창의 평균 이동 속도가 2.5배 이상 다르면 속도 변화 의심 구간으로 표시합니다.
속도 변화 창은 반 창 간격으로 겹쳐 조사합니다. 창·비율·정지 길이는
`inspect-motion --window`, `--change-ratio`, `--freeze-seconds`로 바꿀 수 있습니다.
겹치는 탐지 창은 하나의 후보로 합치고 모든 후보를 보고·미리보기 출력합니다.
후보가 없으면 빈 목록을 정상적으로 반환하며 결함을 만들어 내지 않습니다.

`motion_report.json`은 원본 SHA-256·분석 버전·설정·결정적인 구간 ID·원본 시간·근거를 저장합니다.
원본이 변경됐거나 보고서의 ID·설정 무결성이 맞지 않으면 재분석을 요구합니다.
알 수 없는 ID, 서로 겹치는 선택, 동일 원본 경로가 입력 순서에 두 번 등장해 적용 위치가
모호한 선택도 거절합니다. 현재 저장된 원본 경로와 실제 입력 경로가 같아야 합니다.

미리보기는 구간 시작·끝을 고정한 단조 시간 곡선의 **제안**입니다.
반복·정지 후보는 구간 중간을 조금 더 빠르게 지나가는 매끄러운 곡선을,
속도 변화 후보는 앞뒤 측정 속도 차이에 따른 시간 재배분 곡선을 사용합니다.
선택 시 B1 시간 곡선에 합성하고 보호 구간·배속 상한·끝 이미지·고정 프레임 예산을 다시 검사합니다.
보호 구간과 겹치거나 보수적인 합성 배속 상한을 넘으면 제외 사유를 기록합니다.
완전히 정적인 구간에는 새 움직임을 만들지 않습니다. 선택해도 실제 프레임이 바뀌지 않으면
`no_effect_after_frame_quantization`으로 보고합니다.

각 후보에는 깨끗한 원본·제안 영상, 위치 표시본, 같은 출력 시계의 나란한 비교가 있습니다.
비교용 추가 배속은 없으며 범위 밖은 검정으로 표시합니다. 최종 `retime` 보고서의
`internal_motion`에는 선택·제외·실제 변경 프레임 수·출처가 기록됩니다.

**탐지는 결함 판정이 아닙니다.** 의도된 정지, 물결·불꽃, 가림, 낮은 해상도나 압축 잡음에서
오탐·미탐이 있을 수 있습니다. 형태 복원·카메라 공간 안정화·AI 프레임 생성은 하지 않습니다.
이 단계의 속도 곡선은 검토용 후보이며 자연스러움을 자동 보장하지 않습니다.

## C: JSON 작업 저장·실행

[예제 JSON](examples/job.json)의 파일 경로와 시간 설정을 실제 입력에 맞게 바꾼 뒤 실행합니다.

```bash
.venv/bin/video-manager validate-job examples/job.json
.venv/bin/video-manager run-job examples/job.json
.venv/bin/video-manager run-job examples/job.json --output outputs/new-job-002
```

`validate-job`은 JSON·미디어·시간 제약·내부 분석 출처를 읽기 전용으로 검사하며 출력 디렉터리를
만들지 않습니다. `run-job`은 사전 검사 후 같은 엔진으로 일괄 실행합니다. 파일 하나가 실패했다고
건너뛰고 전체 성공으로 표시하지 않습니다. 실패·취소는 비정상 종료와 상태 파일로 기록합니다.
원래 JSON에 적힌 상대 경로는 **JSON 파일 위치 기준**, CLI `--output` 재정의는 실행 위치 기준입니다.

버전 1의 필드와 기본값:

| 위치 | 필드 |
| --- | --- |
| 최상위 | `schema_version: 1`, `output`, 순서 있는 `clips`, 선택적 `boundaries`, `internal_motion` |
| `output` | 필수 `directory`, `fps`(생략/null이면 첫 원본, 지정 시 1~120), `audio_mode: "mute"` |
| 각 clip | 필수 `id`, `path`, `target_seconds`; `protect_seconds: 1`, `max_speed: 12`, `ramp_seconds: 0.5`, `correction_enabled: true` |
| 각 boundary | 필수 `from`, `to`; `enabled: true`, `mode: "manual"`, `window_seconds: 0.5`, `strength: 0.3`, `local_speed: false`, `duplicate_policy: "review"` |
| `internal_motion` | `reports: []`(분석 보고서 경로), `selected_ids: []`, `excluded_ids: []` |

클립 ID는 중복 없는 1~48자의 영문·숫자·밑줄·하이픈입니다. `baseline`, `corrected`, `comparison`으로
시작하거나 `_diagnostic`으로 끝나는 예약 파일명은 거절합니다. 파일 경로에는 공백·한글을 사용할 수 있습니다.
경계 정의는 실제 인접 클립의 순서를 따라야 하며 생략한 경계는 기본값을 사용합니다.
각 경계의 창·강도·활성·국소 배속 설정을 따로 적용하고 비교 구간도 해당 창에 맞춥니다.
클립 비활성화는 해당 클립의 압축과 양쪽 경계 보정에 우선합니다.

`duplicate_policy`는 `review`, `keep`, `remove`를 받습니다. B1 고정 예산 모드의 `remove`는
끝 이미지·보호·길이를 우선하므로 제거 보류 사유를 결과에 기록합니다. `mode`는 현재 `manual`,
오디오는 `mute`만 지원하며 다른 값은 거절합니다. 알 수 없는 키·잘못된 타입·중복 JSON 키·NaN·Infinity·
중복 ID·비인접 경계·파일 누락·기존 출력·오래된 내부 분석 선택도 실행 전에 거절합니다.

성공 결과에는 `executed_job.json`(절대 경로로 정규화한 실제 설정), 원본 JSON과 정규화 설정의
식별 해시, 입력 해시, 도구 버전, F1~F4 보고서와 클립별·전체 출력이 있습니다.
실패하면 작업별 임시 경로에 실행 설정과 진단 자료를 보존합니다. 재실행은 새 출력 경로를 지정합니다.

코드에서 UI와 같은 API를 사용할 수 있습니다.

```python
from video_manager.job_schema import load_job, normalize_job, validate_job, save_job, run_job
config = load_job("job.json")
config, checks = validate_job(config)  # 출력 생성 없음
save_job(config, "copies/job.json")  # 새 위치 기준 상대 경로로 저장
result = run_job(config, output_override="outputs/new-job")
```

`save_job`은 기본적으로 기존 파일을 덮어쓰지 않습니다. 명시적 `overwrite=True`에서도 원본 클립과
참조한 내부 분석 보고서를 보호합니다. 설정의 실제 영상 자연스러움은 JSON 검증과 별도입니다.

## D: 선택 설치하는 데스크톱 UI

```bash
.venv/bin/python -m pip install -r requirements-ui.txt
.venv/bin/video-manager gui
# 화면 서버가 없는 Linux의 기능 테스트:
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests/ui -v
```

UI 의존성은 PySide6 6.8.2.1로 고정했으며 CLI만 쓸 때는 설치하지 않아도 됩니다.
일반 화면 표시에는 데스크톱 세션이 필요합니다. Linux offscreen 기능 검증을 수행했으며
Windows 실행 파일·설치 프로그램이나 실제 Windows 동작을 검증했다고 주장하지 않습니다.

- **Clips & timing:** 클립 추가·삭제·순서 변경, 원본 길이, 목표·보호·배속 상한·전환 폭·활성 여부,
  새 출력 경로와 공통 FPS를 편집합니다. 원본 정보 읽기는 별도 스레드에서 실행합니다.
- **제작 Master 시간표:** 로컬 MP4를 먼저 추가한 뒤 `Load JSON`에서 `I2V_30Clips_Master.json`을
  선택하면 파일명의 `01_02.mp4` 또는 `SC01 · 01-02.mp4` 같은 장면·컷 번호를 `records[].scene`과 `records[].cut`에
  맞춰 `edit_duration_s`를 Target에 채웁니다. 클립 경로·순서·출력 경로와 기존 경계 설정은 유지합니다.
  일치하지 않는 파일명, 빠진 컷, 중복 컷 또는 `start_s`/`end_s`와 목표 시간의 불일치가 있으면
  적용 전에 오류를 표시합니다. Master에는 MP4 경로가 없으므로 클립을 먼저 추가해야 합니다.
  적용 후 `Save JSON`은 실제 렌더 작업 형식의 별도 JSON을 저장합니다. `Index.csv`와 검토용 HTML은
  시간표 확인 자료이며 이 버튼에서 직접 가져오지는 않습니다.
- **Boundaries:** 인접 경계별 활성·창·강도·국소 변속·중복 정책을 조절합니다.
- **Internal motion:** Inspect motion으로 별도 분석 작업을 시작하거나 보고서를 불러옵니다.
  구간 시간·종류·근거를 보고 선택·제외 체크를 지정합니다. 행을 두 번 클릭하면 제안 비교를 엽니다.
- **Review & results:** 하나로 결합된 비교 영상을 공통 시계로 재생·일시정지·탐색·프레임 이동·반복합니다.
  원본·출력 위치는 영상에 표시됩니다. 클립별 시작·끝·실측 길이·오차와 기본 속도 곡선을 확인합니다.
  Load results로 기존 작업 폴더를 열 수도 있습니다.

Load/Save JSON과 실행은 C의 동일한 검증·저장 API를 사용합니다. 설정 변경 시 이전 결과를
`stale`로 표시하며, 이전 설정으로 실행 중이던 작업이 끝나도 새 설정 결과라고 표시하지 않습니다.
분석 보고서의 원본이 바뀌면 선택을 거절합니다. 곡선은 보호·전환 폭·목표·배속 값을 편집하고
재실행하여 갱신하며, 그래프는 기본 압축 곡선입니다. 합성한 경계·내부 조절은 결과 보고서에 따로 기록합니다.

렌더링·내부 분석은 GUI와 분리된 작업 프로세스에서 수행합니다. 진행률은 엔진이 실제 세부 비율을
제공하지 않으므로 실행 중 표시를 사용합니다. Linux Cancel은 작업 프로세스 그룹에 SIGINT를 보내
정리를 기다리고, 취소 결과를 성공 영상으로 공개하지 않습니다. 오류와 작업 로그를 화면에 표시합니다.
출력은 음소거이며 원본 파일을 수정하지 않습니다.

### 압축 후 연결부 속도 계획 보완

B1의 경계 조절은 원본 측정 속도에 **기본 압축 곡선의 경계 배속**을 곱한 유효 속도로 계획합니다.
다음 클립 시작이 보호 구간이면 그쪽 속도를 고정하고 이전 클립 끝 조절을 그 속도에 맞추는 후보로 계산합니다.
따라서 10초→3초 압축으로 이미 빨라진 끝부분을 원본 속도만 보고 더 가속하는 오류를 피합니다.
보고서 `velocity_planning`에 원본 속도·유효 속도·목표와 판단 이유를 남깁니다. 실제 움직임 추정은
여전히 휴리스틱이며 육안상 자연스러움을 보장하지 않습니다.
