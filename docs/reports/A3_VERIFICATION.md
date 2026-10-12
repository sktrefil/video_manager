# A3 독립 검증 보고서

판정: **통과 (A3, F1 보정 매핑, F2 비교, F3 제외 제어)**. 제품 코드를 수정하지 않고 고정 상태를 검증했다.

## 실행 증거

- `.venv/bin/python -m unittest discover -s tests/verification -p test_a3_independent.py -v`: 독립 통합 시나리오 2개 통과.
- `.venv/bin/python -m unittest discover -s tests/integration -v`: 기존 통합 테스트 8개 독립 재실행 통과.
- 설치된 CLI `boundaries`를 3클립 시퀀스로 실행. 고속→저속→역방향 사례에서 실제 보정 출력 전체 프레임을 독립 FFmpeg RGB 디코딩하여 보고서가 지정한 원본 프레임과 평균 픽셀 오차 4 미만으로 대조.
- 속도 제어 적용 시 프레임 스케줄 실제 변경, 클립별 단조성·첫/끝 프레임 보존 확인.
- 클립 2 제외, 경계 1·2 제외, 클립 1과 경계 2 동시 제외 조합에서 보정 일정이 기본과 동일하고 중복 제거도 억제됨을 확인.
- 역방향 충돌·정지/낮은 신뢰도 사례에서 속도 보정 미적용 확인.
- 공유 경계 3클립에서 다음 클립 원본 프레임 0만 제거되고 이전 클립 마지막 대표 프레임 유지, 길이 30→28프레임 확인.
- F2의 모든 비교 프레임에서 양쪽 경계 상대 프레임과 보고서 출력 프레임의 일치 확인. 실제 비교 영상의 하단 영역을 해당 진단 영상 프레임과 대조하여 추가 변속 없이 같은 시계로 표시됨을 검증. 범위 밖은 실제 검정 영역이며 정지 프레임 연장 없음.
- 기존 테스트로 무보정·강도 0, 불량 옵션, 원본 해시 보존 및 대표 프레임 보고 항목도 재검증.

## 제한

재현 가능한 A3 필수 기준 결함 없음. 광학 흐름 수치와 합성 검사는 실제 생성 영상의 자연스러움을 입증하지 않는다. A4 실제 샘플·사용자 품질 확인, B 압축·F4는 미검증이며 다음 단계 게이트를 유지한다.

## 검증 대상 SHA256

| 파일 | SHA256 |
| --- | --- |
| `src/video_manager/__init__.py` | `a55e73c3a9d7b92cc06825176e0e0d7c2b6a2bec66bbf9a048c7b934b5a27716` |
| `src/video_manager/__main__.py` | `935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d` |
| `src/video_manager/boundary.py` | `b2a1de14de195fd4c62ed81438927d0e45fa2de2a6b4ddfe1b00e49b2bb1e057` |
| `src/video_manager/cli.py` | `dc7b77b44b6ccff26e3e53e94c4f0bd2ae55fb2aa87a3e87733c5720ef39ed96` |
| `src/video_manager/comparison.py` | `e576391ea9f0637fb98e57f46a5719135fdf23ebc97d6e09de72df6236de1cec` |
| `src/video_manager/errors.py` | `fd9f506bf31fa9872f1a6acdcc60ca26de35c6ea5c77db546de4752908982e08` |
| `src/video_manager/pipeline.py` | `4261940100daccb6b1465a400d7b5dddac54bfc0ed339852e9b698d88b3b00c6` |
| `src/video_manager/probe.py` | `39a3e2365a65ef0fb343a14d8f75129f38238e9a7aacf420e944169fcc606a2f` |
| `src/video_manager/render.py` | `ad49621f3513f5a4abee8d19f681817774c1ed0b511932856bda509332867eb6` |
| `src/video_manager/report.py` | `442e007518097904f42dada9bafb0422c2c9bf971eb1b8908755a0cc4b63bb13` |
| `src/video_manager/tools.py` | `4fc995a8645ec6664709582c0368e8ffe005228f35eb7dd336f65799dc4442b6` |
| `pyproject.toml` | `3c29cb7849f734f4842b3d8177542b19d221590a10be8e59faed750610fc6c9c` |
| `requirements-dev.txt` | `ba8a94ddb0dea8bc727be3a27f291ecd197398424ad567dd8c86a7e80334a9db` |
| `README.md` | `3c0b0983241b0a72634538e5d55f6fba81760fafeac3bfb49fc9f72c616fc7e9` |
