# A1 독립 검증 보고서

판정: **통과 (A1 범위)**. 구현 담당과 별도 검증 작업자가 실행했다. 제품 코드는 수정하지 않았다.

## 실행 증거

- `.venv/bin/python -m unittest discover -s tests/unit -v`: 자체 테스트 7개 직접 재실행, 통과.
- `.venv/bin/python -m unittest discover -s tests/verification -p test_a1_independent.py -v`: 독립 테스트 6개 통과.
- `.venv/bin/video-manager doctor`: ffmpeg/ffprobe 7.1.5, libx264 확인.
- 설치된 CLI 도움말, PATH 격리를 통한 ffmpeg·ffprobe 개별 누락(종료 3), 부족·빈·디렉터리·없는 입력(종료 2) 확인.
- 한글·공백 경로, 역순 입력 순서 보존, 원본 SHA256 불변, 재실행 결과 불변, 기존 입력·디렉터리·깨진 심볼릭 링크 덮어쓰기 거절 확인.
- 별도 Python 프로세스에서 처리 예외 및 KeyboardInterrupt를 주입하여 실패/취소 상태, 진단 파일 보존, results 미공개 확인. 실제 렌더러 프로세스의 신호 취소는 후속 단계 검증 대상이다.

## 범위와 제한

A1은 읽을 수 있는 비어 있지 않은 일반 파일의 경로 검증만 수행한다. 실제 영상 디코딩·프레임 추적·연결부 품질·시간 압축은 통과 판정 대상이 아니며 A2 이후 검증한다. A1 범위 내 재현 가능한 필수 기준 실패 없음.

## 검증 대상 SHA256

다음 식별값은 이번 검증에서 읽고 실행한 코드·구성·안내 상태다. 이후 변경 시 해당 변경 영향은 다시 검증한다.

| 파일 | SHA256 |
| --- | --- |
| `src/video_manager/__init__.py` | `a55e73c3a9d7b92cc06825176e0e0d7c2b6a2bec66bbf9a048c7b934b5a27716` |
| `src/video_manager/__main__.py` | `935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d` |
| `src/video_manager/cli.py` | `de7a2425b856f08f0c0e44eb69b1693583271afd3e80e3e0df0fa4e17c489f4d` |
| `src/video_manager/errors.py` | `fd9f506bf31fa9872f1a6acdcc60ca26de35c6ea5c77db546de4752908982e08` |
| `src/video_manager/pipeline.py` | `6f0eb1a2fc5e1512e6fd11cd1d7121a223840f7fcde11d048846c153fbd3a79d` |
| `src/video_manager/tools.py` | `4fc995a8645ec6664709582c0368e8ffe005228f35eb7dd336f65799dc4442b6` |
| `pyproject.toml` | `27e0c626b59d3fafb3f75773f522b1a2db08bd6922433903225c05693cc67ff8` |
| `requirements-dev.txt` | `21df682155f0d210151bcaa5996d838e5bc9dbc757b7ff466eaebef3a9cbe078` |
| `README.md` | `ba8095957803b6181f8323d57709963776fefadbc25adc6ed3424c4b8f078eb2` |
| `.gitignore` | `e0d2a9c08d7eb9a0fec1d050ea03857ac7eae32dd58536f3a87f1d1809a888cc` |
| `tests/unit/test_foundation.py` | `13993b608bc35c8d65ce7645d88dbc9554bed475afddbed4f4ae2239d4c4fe01` |
