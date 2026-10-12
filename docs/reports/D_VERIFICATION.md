# D 독립 검증 보고서

판정: **D Linux offscreen 기술 검증 통과 / 실제 데스크톱·Windows 및 시각 품질 미승인**.

## 실행 결과

| 명령 | 결과 |
| --- | --- |
| `.venv/bin/python -m unittest discover -s tests/verification -p test_d_independent.py -v` | 독립 2 통과 |
| `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests/ui -v` | UI 독립 재실행 3 통과 |

UI 검사 중 fontconfig 캐시·offscreen 플러그인 경고가 출력되었으나 작업 및 검사 결과는 정상이다.

## 확인 내용

- 실제 QProcess 엔진 작업을 실행하고 완료 신호·출력 보고서·설정 반영·3.5초 실측 결과를 확인. 렌더 중 10ms 타이머가 지속 동작하여 이벤트 루프 응답 확인.
- 실제 작업 시작 후 취소하여 cancelled 상태와 results 미공개 확인. 가짜 완료 신호로 대체하지 않았다.
- 클립 순서·목표·보호·경계 활성·내부 선택/제외 JSON 저장 및 재로드 일치, 오래된 원본 출처 거절 후 화면 응답 유지 확인.
- 결과 변경 시 stale 표시, 공통 비교 영상 프레임 앞뒤 이동과 끝에서 반복 재생 확인.
- 별도 Python 프로세스에서 core CLI doctor 실행 후 PySide6가 sys.modules에 없는 것을 검사하여 CLI의 선택적 UI 의존성 지연 로딩 확인.

## 압축 후 경계 속도 회귀

독립 합성 사례는 왼쪽 원본 5초·오른쪽 2초를 각 2초로 맞추었다. 원본 측정에서는 왼쪽이 느리지만 압축 후 유효 속도는 왼쪽이 더 빨라진다. 보정 계획이 왼쪽 alpha<0으로 감속하고 오른쪽 보호 구간은 유지하는지 확인했다. 실제 출력 80프레임/4초, 처음 0.5초 보호 매핑·각 끝 프레임·합성 배속 상한도 통과했다.

초기 독립 픽스처는 이동량이 작아 정수 위치 반복과 중앙값 광학 흐름 0이 발생해 의도한 속도 관계를 구성하지 못했다. 제품 결함으로 판정하지 않고, 측정 가능한 이동량의 합성 픽스처로 바꾼 뒤 위 회귀를 검증했다.

## 제한과 다음 단계

제품 코드는 수정하지 않았다. 실제 사용자 파일은 이번 검증에서 처리하지 않았다. offscreen은 실제 모니터·GPU·OS 파일 대화상자 및 Windows 배포 검증을 대신하지 않는다. 실제 결과 제작을 진행할 수 있으나 정상 속도 자연스러움은 사용자 검토 대상으로 남는다.

## 검증 대상 SHA256

| 파일 | SHA256 |
| --- | --- |
| `src/video_manager/__init__.py` | `a55e73c3a9d7b92cc06825176e0e0d7c2b6a2bec66bbf9a048c7b934b5a27716` |
| `src/video_manager/__main__.py` | `935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d` |
| `src/video_manager/boundary.py` | `010305e2590cbc15fe309d0d13483ee877b784be99ed5a2401857391e78e205a` |
| `src/video_manager/cli.py` | `f8f7c2c2332cea0ba7598d4fa6865e4f57a0c9141e6fc1039b3a3fd83365796e` |
| `src/video_manager/comparison.py` | `f7e7240365e934fbb55979b92320e497e143ae44510fe6573a94967481f951b4` |
| `src/video_manager/errors.py` | `fd9f506bf31fa9872f1a6acdcc60ca26de35c6ea5c77db546de4752908982e08` |
| `src/video_manager/internal_motion.py` | `3f044b2e7d7a41dd957318a7777e15e6a2d9833441fba07b8ab63d179e8a3ce5` |
| `src/video_manager/job_schema.py` | `26f29fcc8c42f1aad168dfbc168936c2f2676e58f40deef3550c2856fa3b99ae` |
| `src/video_manager/pipeline.py` | `4261940100daccb6b1465a400d7b5dddac54bfc0ed339852e9b698d88b3b00c6` |
| `src/video_manager/probe.py` | `39a3e2365a65ef0fb343a14d8f75129f38238e9a7aacf420e944169fcc606a2f` |
| `src/video_manager/render.py` | `289adf339a858a6ffd037452322682310d6a29d8247d3a37e61903a399486e51` |
| `src/video_manager/report.py` | `442e007518097904f42dada9bafb0422c2c9bf971eb1b8908755a0cc4b63bb13` |
| `src/video_manager/retime.py` | `d5140a1a249e23d222c4d0dff0845f576eb05d9ba21d7bddb1ea552ba576d4f9` |
| `src/video_manager/time_map.py` | `095268ff6bc975c94e430da8ade786f1b005cadea71b1d160cbcea402b8e92e6` |
| `src/video_manager/tools.py` | `4fc995a8645ec6664709582c0368e8ffe005228f35eb7dd336f65799dc4442b6` |
| `src/video_manager/ui/__init__.py` | `c6f5d0940cb2ac5cdc416147a409ac5c2a7fc427ea0961b67e77a2d64ba64e09` |
| `src/video_manager/ui/app.py` | `74a36d8fcb7a1791479d47655b7be78410d79de711723531861ef96114c3646f` |
| `src/video_manager/ui/viewer.py` | `90663f551e2969bd9ece0a98f1a96c9ff62017e7be67fb408c4ceab37fb97b69` |
| `src/video_manager/ui/worker.py` | `630af5f170095cbb6784667da6d56e7fa5b583e0b27fffd523cbe9ace61b6dce` |
| `pyproject.toml` | `1f6e34e9598633c037bf33eb91d40e5946bd61b2c78dac75ccf0941f6021ad81` |
| `requirements-dev.txt` | `ba8a94ddb0dea8bc727be3a27f291ecd197398424ad567dd8c86a7e80334a9db` |
| `README.md` | `41a071678ca3a47af6b5d4dc12cfe8456825639785a718dc1cdae7bf9fe47343` |
