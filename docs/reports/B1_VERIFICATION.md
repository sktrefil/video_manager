# B1 독립 검증 보고서

판정: **B1 기술 검증 통과 / 실제 시각 품질 미승인**. 제품 코드 변경 없이 독립 실행했다. 사용자 지시에 따라 기술 통과 후 B2→C→D를 계속할 수 있으며 실제 결과의 품질 승인을 의미하지 않는다.

## 실행 결과

| 명령 | 결과 |
| --- | --- |
| `.venv/bin/python -m unittest discover -s tests/verification -p test_b1_independent.py -v` | 독립 테스트 2 통과 |
| `.venv/bin/python -m unittest discover -s tests/unit -v` | 11 통과 |
| `.venv/bin/python -m unittest discover -s tests/integration -p test_retime.py -v` | B1 통합 3 통과 |

영향 범위 중심 총 16개 통과. 변경 없는 A 전체 회귀는 반복하지 않았다.

## 독립 검증 내용

- 설치된 CLI retime로 합성 원본 10/4/10초를 3/4/4초(11초), 10/10초를 4/4초(8초)로 출력. 실제 디코딩 프레임 220/160개(20fps) 및 모든 출력 PTS를 독립 ffprobe로 확인.
- 각 클립 처음 1초 보호 구간의 모든 프레임과 최종 프레임을 독립 FFmpeg RGB 디코딩해 실제 원본과 대조. 원본 선택 번호 일치, 평균 픽셀 오차 4 미만. 단순 보고서만으로 판정하지 않았다.
- 10→3초의 보호 종료 시 1배속 연속성, 마지막 표시 시각 대응, 단조성 확인. 경계 곡선 합성 후 20,000개 수치 구간의 실제 기울기가 보수적 최대 배속 이내인지 확인.
- A3 시작 보정이 보호 구간과 겹칠 때 제외, 끝 보정 합성, 배속 상한 충돌 제외 확인.
- 3/10/101개 소수 목표의 공동 프레임 배분에서 개별·합계 오차 한 프레임 이내, 누적 반올림 오차 방지 확인.
- bool/문자열/None/NaN/무한대/음수/0 목표 거절; 보호≥목표, 보호>원본(identity 포함), 배속 부족, 과도한 전환폭, 늘리기, 비활성화 클립 압축 충돌 거절 확인.
- 기존 B1 통합 테스트 독립 재실행으로 10→4·6→5, VFR·비영 시작 PTS·혼합 FPS·실제 소수 목표 출력, 오디오 보존 요청 거절을 검증.

## 범위와 제한

재현 가능한 B1 필수 기술 기준 결함 없음. 중복 제거 요청은 현재 프레임 예산·보호·끝 이미지 제약을 우선해 미적용 사유를 보고하는 정책이며 실제 제거를 했다고 판정하지 않았다. 실제 업로드 영상은 이번에 처리하지 않았다. 사용자 시각 품질 확인 및 B2 내부 후보·JSON·UI는 별도 단계다.

## 검증 대상 SHA256

| 파일 | SHA256 |
| --- | --- |
| `src/video_manager/__init__.py` | `a55e73c3a9d7b92cc06825176e0e0d7c2b6a2bec66bbf9a048c7b934b5a27716` |
| `src/video_manager/__main__.py` | `935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d` |
| `src/video_manager/boundary.py` | `010305e2590cbc15fe309d0d13483ee877b784be99ed5a2401857391e78e205a` |
| `src/video_manager/cli.py` | `53088f63d29961dc3c34a43eb6fb6a299ce0591a3ae2e9000cf24ee7c3c70007` |
| `src/video_manager/comparison.py` | `e576391ea9f0637fb98e57f46a5719135fdf23ebc97d6e09de72df6236de1cec` |
| `src/video_manager/errors.py` | `fd9f506bf31fa9872f1a6acdcc60ca26de35c6ea5c77db546de4752908982e08` |
| `src/video_manager/pipeline.py` | `4261940100daccb6b1465a400d7b5dddac54bfc0ed339852e9b698d88b3b00c6` |
| `src/video_manager/probe.py` | `39a3e2365a65ef0fb343a14d8f75129f38238e9a7aacf420e944169fcc606a2f` |
| `src/video_manager/render.py` | `ad49621f3513f5a4abee8d19f681817774c1ed0b511932856bda509332867eb6` |
| `src/video_manager/report.py` | `442e007518097904f42dada9bafb0422c2c9bf971eb1b8908755a0cc4b63bb13` |
| `src/video_manager/retime.py` | `df4af3d3c12e05e0d1aabb37c0407659c1fadc786773f4502ca6977114f69142` |
| `src/video_manager/time_map.py` | `eba97db5e3116c1804b9aea315376f1e736106b5460095644917065e57aadc4e` |
| `src/video_manager/tools.py` | `4fc995a8645ec6664709582c0368e8ffe005228f35eb7dd336f65799dc4442b6` |
| `pyproject.toml` | `3c29cb7849f734f4842b3d8177542b19d221590a10be8e59faed750610fc6c9c` |
| `requirements-dev.txt` | `ba8a94ddb0dea8bc727be3a27f291ecd197398424ad567dd8c86a7e80334a9db` |
| `README.md` | `05571e7c43166f0c95ea430cdf7495badbee9e0a967d39bc8607a8f705b6ba16` |
