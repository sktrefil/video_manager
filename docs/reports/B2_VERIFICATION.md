# B2 독립 검증 보고서

판정: **B2 기술 검증 통과 / 실제 자연스러움 미승인**. 제품 코드 수정 없음.

## 실행 결과

| 명령 | 결과 |
| --- | --- |
| `.venv/bin/python -m unittest discover -s tests/verification -p test_b2_independent.py -v` | 독립 CLI 시나리오 1 통과 |
| `.venv/bin/python -m unittest discover -s tests/integration -p test_internal_motion.py -v` | B2 통합 3 통과 |
| `.venv/bin/python -m unittest discover -s tests/verification -p test_a3_independent.py -v` | 비교 라벨 변경 영향 2 통과 |
| `.venv/bin/python -m unittest discover -s tests/verification -p test_b1_independent.py -v` | TimeMap 변경 영향 2 통과 |

총 8개 통과. 무관한 A1/A2 회귀는 반복하지 않았다.

## 실제 실행 검증

- 설치된 `inspect-motion` CLI로 정지·반복 구간 포함 합성 클립과 정상 이동 클립 분석. 정상 이동은 후보 없음, 반복 후보는 기본 미선택.
- 원본·제안 미리보기의 모든 프레임을 독립 FFmpeg RGB 디코딩하여 해당 원본 프레임과 실제 픽셀 대조(평균 오차 4 미만).
- 비교 영상 모든 유효 양쪽 프레임의 하단 픽셀을 각각 진단 영상과 비교해 공통 출력 시계·추가 변속 없음 확인.
- 설치된 retime CLI로 기본/선택/선택+제외 3개 실행. 선택 시 실제 소스 스케줄 변경, 기본과 제외는 스케줄 완전 동일. 선택 출력 전체 프레임을 원본과 픽셀 대조.
- 4+4초 고정 예산 160프레임(20fps), 각 클립 처음 1초 보호 프레임 및 마지막 원본 프레임 보존 확인. 알 수 없는 ID CLI 종료 2 및 성공 결과 미생성 확인.
- B2 통합 테스트를 독립 재실행하여 속도 변화 탐지, 정지 후보의 무동작 생성 방지, 보호 구간 충돌 제외, 보고서 변조·원본 해시 변경·알 수 없는 ID·겹치는 선택 거절 확인.
- 영향받은 A3 비교 시계/경계 제외와 B1 11초·8초/보호/배속 상한 검증을 재실행하여 통과.

## 범위와 한계

실제 업로드 영상은 처리하지 않았다. 후보는 의도된 정지와 결함을 자동 확정하지 않으며, 검증은 원본 대응·선택 제어·길이 보존의 기술적 정확성이다. 시각적으로 개선되었다고 승인하지 않는다. 다음 C JSON 구현 진행 가능.

## 검증 대상 SHA256

| 파일 | SHA256 |
| --- | --- |
| `src/video_manager/__init__.py` | `a55e73c3a9d7b92cc06825176e0e0d7c2b6a2bec66bbf9a048c7b934b5a27716` |
| `src/video_manager/__main__.py` | `935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d` |
| `src/video_manager/boundary.py` | `010305e2590cbc15fe309d0d13483ee877b784be99ed5a2401857391e78e205a` |
| `src/video_manager/cli.py` | `bc1533be82913c03e89fdbaccbcd3dedf55ef1981c824221084d3d721b8e858e` |
| `src/video_manager/comparison.py` | `cc864a5144f2b601aade7a9d5598e24b879b204fcc4be7b1a9e52caa1829a90e` |
| `src/video_manager/errors.py` | `fd9f506bf31fa9872f1a6acdcc60ca26de35c6ea5c77db546de4752908982e08` |
| `src/video_manager/internal_motion.py` | `3f044b2e7d7a41dd957318a7777e15e6a2d9833441fba07b8ab63d179e8a3ce5` |
| `src/video_manager/pipeline.py` | `4261940100daccb6b1465a400d7b5dddac54bfc0ed339852e9b698d88b3b00c6` |
| `src/video_manager/probe.py` | `39a3e2365a65ef0fb343a14d8f75129f38238e9a7aacf420e944169fcc606a2f` |
| `src/video_manager/render.py` | `ad49621f3513f5a4abee8d19f681817774c1ed0b511932856bda509332867eb6` |
| `src/video_manager/report.py` | `442e007518097904f42dada9bafb0422c2c9bf971eb1b8908755a0cc4b63bb13` |
| `src/video_manager/retime.py` | `89732997edba69cf4ece9ebe3b747464beab4f2f8bd5895386c8a5da98494de5` |
| `src/video_manager/time_map.py` | `095268ff6bc975c94e430da8ade786f1b005cadea71b1d160cbcea402b8e92e6` |
| `src/video_manager/tools.py` | `4fc995a8645ec6664709582c0368e8ffe005228f35eb7dd336f65799dc4442b6` |
| `pyproject.toml` | `3c29cb7849f734f4842b3d8177542b19d221590a10be8e59faed750610fc6c9c` |
| `requirements-dev.txt` | `ba8a94ddb0dea8bc727be3a27f291ecd197398424ad567dd8c86a7e80334a9db` |
| `README.md` | `8ed9f07355d993607b4c38a7c6cf3566ef1555590cd3a83a0810936cb880b5b4` |
