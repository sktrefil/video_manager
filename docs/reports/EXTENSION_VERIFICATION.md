# 원본보다 긴 목표 시간 독립 검증

판정: **4→5초 늘리기 기술 검증 통과**. 제품 코드를 수정하지 않았다.

## 실행

- `.venv/bin/python -m unittest discover -s tests/verification -p test_extension_independent.py -v`: 독립 2개 통과.
- `.venv/bin/python -m unittest discover -s tests/unit -p test_time_map.py -v`: 시간 매핑 5개 독립 재실행 통과.
- `.venv/bin/python -m unittest discover -s tests/verification -p test_b1_independent.py -v`: 기존 11/8초 압축 회귀 2개 통과.
- `QT_QPA_PLATFORM=offscreen`에서 SpeedPlot에 늘리기 모델을 전달해 실제 화면 픽셀의 파란 곡선이 오른쪽으로 내려가는지 검사하여 감속 그래프 표시 확인.

총 자동 테스트 9개와 별도 offscreen 곡선 픽셀 검사 통과. 새 요구와 충돌하는 기존 B1 독립 테스트의 “10→11초 무조건 거절” 기대만 제거했다. 다른 유효성 기준은 유지했다.

## 실제 검증 내용

- 24fps 합성 원본 4초 두 개를 각각 5초로 출력. 최종 실제 디코딩 240프레임/10초, 클립별 120프레임 확인.
- 처음 1초의 0~24 원본 프레임 그대로 유지, 전체 원본 매핑 단조 증가/반복, 마지막 원본 프레임 95 포함.
- 최종 240개 프레임 전체를 원본 해당 프레임과 실제 RGB 픽셀 비교(평균 오차 4 미만).
- 추가 반복 프레임이 후반 여러 1초 구간에 분산되고 끝 프레임 반복이 2개 이하임 확인. 마지막 정지 화면만 1초 붙이는 방식이 아님.
- 보호 종료 시 1배속 연속, 이후 양의 속도로 매끄럽게 감속, 마지막 표시 시각 대응 확인.
- 종단 속도가 1 미만이어도 speed_bound=1 이상 유지. 최대 배속 1 설정에서 추가 경계 보정이 상한을 넘으면 제외함 확인.
- 보호 구간이 원본을 소진하거나 전환 폭이 불가능한 경우, 비활성 클립 늘리기 충돌 거절 확인.
- 기존 10→3초 수식·보호 구간·끝 프레임 유지 및 실제 11초/8초 압축 회귀 통과.

## 한계

보간 프레임을 생성하지 않고 실제 원본 프레임을 선택·반복하므로, 늘린 영상에 반복에 의한 끊김이 보일 수 있다. 기술 검증을 시각적 자연스러움 승인으로 표시하지 않는다. 해당 실제 Master 클립 파일이 없어 이번에는 합성 영상으로 검증했다. Windows UI 및 배포 실행은 검증하지 않았다.

## 검증 상태 SHA256

| 파일 | SHA256 |
| --- | --- |
| `src/video_manager/time_map.py` | `dad0809b78b62bb5f9c685e5a6c7e14393efb69446681e6135db1a5eded66f9b` |
| `src/video_manager/ui/viewer.py` | `904a884bb0e9ad028952935ea2cf95b5bdc5b40286770d133d097cd52f33b6bd` |
| `tests/verification/test_extension_independent.py` | `2a2970e9be60025148e5e5aacb4a36e067a50699782d2586e94f70147d4defbc` |
| `tests/verification/test_b1_independent.py` | `694a887d0c5d775ebd1614793177c3a00392e5ab645e86fd765188724e9a903b` |
