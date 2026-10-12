# A2 독립 검증 보고서

판정: **통과 (A2 및 F1 기준 정보)**. 제품 코드 변경 없이 독립 실행했다.

## 실행과 증거

- `.venv/bin/python -m unittest discover -s tests/verification -p test_a2_independent.py -v`: 독립 통합 시나리오 1개 통과.
- `.venv/bin/python -m unittest discover -s tests/integration -v`: 구현 담당 통합 테스트 3개 독립 재실행 통과.
- `.venv/bin/python -m unittest discover -s tests/unit -v`: 기반 테스트 7개 재실행 통과.
- 독립 생성한 3클립 시퀀스: 2초 비영 시작 PTS·VFR·고유 회색값 프레임 ID 입력, 혼합 FPS·세로 비율·오디오 입력, 첫 입력 반복. 설치된 CLI baseline 직접 실행.
- 제품 디코더를 사용하지 않고 FFmpeg raw RGB로 최종 출력 전체 프레임을 디코딩하여 원본 고유 회색값 ID와 보고서 선택 프레임·실제 PTS를 대조. 반복 선택·첫/마지막 ID 확인.
- 입력 순서, 한글/공백 경로, 좌우 패딩 픽셀, 음소거 출력, 진단 글자 존재 및 최종 제작본 글자 없음, 경계 구간 디코딩·길이 확인.
- 원본 SHA256 불변, 같은 경로 재실행 거절 및 보고서 불변, 잘못된 미디어 종료 코드 2·실패 상태·결과 미공개 확인.

## 제한과 다음 단계

재현 가능한 A2 필수 기준 결함 없음. 실제 영상 품질과 A3 보정·F2/F3, B 시간 압축·F4는 이번 판정 범위가 아니다. 합성 입력으로 구현 동작만 검증했다.

## 검증 대상 SHA256

| 파일 | SHA256 |
| --- | --- |
| `src/video_manager/__init__.py` | `a55e73c3a9d7b92cc06825176e0e0d7c2b6a2bec66bbf9a048c7b934b5a27716` |
| `src/video_manager/__main__.py` | `935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d` |
| `src/video_manager/cli.py` | `2ad91cc51cb04684ca822c94c5ead13ef7a1e6243ec9ea81d345097f3005b3d4` |
| `src/video_manager/errors.py` | `fd9f506bf31fa9872f1a6acdcc60ca26de35c6ea5c77db546de4752908982e08` |
| `src/video_manager/pipeline.py` | `5adc6d22c64e4953e2778e70e95270044a4b742c131c59ce58262d41e459cea0` |
| `src/video_manager/probe.py` | `39a3e2365a65ef0fb343a14d8f75129f38238e9a7aacf420e944169fcc606a2f` |
| `src/video_manager/render.py` | `ad49621f3513f5a4abee8d19f681817774c1ed0b511932856bda509332867eb6` |
| `src/video_manager/report.py` | `442e007518097904f42dada9bafb0422c2c9bf971eb1b8908755a0cc4b63bb13` |
| `src/video_manager/tools.py` | `4fc995a8645ec6664709582c0368e8ffe005228f35eb7dd336f65799dc4442b6` |
| `pyproject.toml` | `e70eeda4b95b64ae81e479f2f3c00feb7ff57372364315c2c4ef837474f230dc` |
| `requirements-dev.txt` | `dafe8a286c5617cc8e3d6a6b0645660cdfde6fdda3789517cbacba9bd3ac68a3` |
| `README.md` | `7da2cd477a93f20f7d24653615018e26f3714a5759a0e7b3e530cc524ffeaa57` |
