# C 독립 검증 보고서

판정: **C 기술 검증 통과 / 실제 품질 미승인**. 제품 수정·실제 업로드 영상 처리 없음.

## 실행 결과

| 명령 | 결과 |
| --- | --- |
| `.venv/bin/python -m unittest discover -s tests/verification -p test_c_independent.py -v` | 독립 CLI 시나리오 1 통과 |
| `.venv/bin/python -m unittest discover -s tests/integration -p test_jobs.py -v` | JSON 통합 4 통과 |
| `.venv/bin/python -m unittest discover -s tests/verification -p test_b2_independent.py -v` | retime/선택 영향 회귀 1 통과 |

총 6개 통과. 변경 없는 무관 단계 검사는 반복하지 않았다.

## 독립 검증 내용

- 한글·공백 입력 경로 및 분석 보고서 상대 경로를 다른 디렉터리의 JSON에 저장하고 재로드하여 정규화된 파일 경로·선택/제외 ID가 동일함을 확인.
- 설치된 validate-job CLI는 출력 폴더를 만들지 않으며 run-job CLI는 지정한 24fps·96프레임·4초를 실제 생성. ffprobe로 FPS·길이를 확인하고 JSON 실행과 API 실행의 전체 디코딩 RGB 픽셀이 동일함을 확인.
- 경계별 0.25초 설정에 따른 12프레임 추출, 경계 비활성 우선순위, 내부 선택+제외의 제외 우선, 기존 출력 재실행 거절 확인.
- 기존 JSON 통합 4개 독립 재실행: 별도 FPS·인접 경계 설정·클립 비활성 우선·직접 엔진과 매핑 일치, 알 수 없는 필드·타입·NaN·중복 JSON 키·중복 ID·비인접 경계·없는 파일·입출력 충돌·깨진 출력 심볼릭 링크 사전 거절 확인.
- save_job overwrite=True에서도 분석 보고서 의존성을 덮어쓰지 않음, 오래된 원본 해시를 렌더 전 거절하고 출력 미생성 확인.
- 처리 실패·KeyboardInterrupt 주입 시 성공 결과 미공개 및 failed/cancelled 상태 확인.
- B2 독립 시나리오 재실행으로 보고서 출처를 사용한 선택·비교 픽셀·보호·끝 이미지·고정 길이 기능의 영향 회귀 통과.

## 범위

재현 가능한 C 필수 기술 기준 결함 없음. JSON 기술 검증을 실제 시각 품질 승인으로 해석하지 않는다. D UI 구현 진행 가능.

## 검증 대상 SHA256

| 파일 | SHA256 |
| --- | --- |
| `src/video_manager/__init__.py` | `a55e73c3a9d7b92cc06825176e0e0d7c2b6a2bec66bbf9a048c7b934b5a27716` |
| `src/video_manager/__main__.py` | `935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d` |
| `src/video_manager/boundary.py` | `010305e2590cbc15fe309d0d13483ee877b784be99ed5a2401857391e78e205a` |
| `src/video_manager/cli.py` | `ca3616b72e0eeec804d561af9df457247482f69ffc9f04c2667dd2bad0a1000a` |
| `src/video_manager/comparison.py` | `f7e7240365e934fbb55979b92320e497e143ae44510fe6573a94967481f951b4` |
| `src/video_manager/errors.py` | `fd9f506bf31fa9872f1a6acdcc60ca26de35c6ea5c77db546de4752908982e08` |
| `src/video_manager/internal_motion.py` | `3f044b2e7d7a41dd957318a7777e15e6a2d9833441fba07b8ab63d179e8a3ce5` |
| `src/video_manager/job_schema.py` | `26f29fcc8c42f1aad168dfbc168936c2f2676e58f40deef3550c2856fa3b99ae` |
| `src/video_manager/pipeline.py` | `4261940100daccb6b1465a400d7b5dddac54bfc0ed339852e9b698d88b3b00c6` |
| `src/video_manager/probe.py` | `39a3e2365a65ef0fb343a14d8f75129f38238e9a7aacf420e944169fcc606a2f` |
| `src/video_manager/render.py` | `289adf339a858a6ffd037452322682310d6a29d8247d3a37e61903a399486e51` |
| `src/video_manager/report.py` | `442e007518097904f42dada9bafb0422c2c9bf971eb1b8908755a0cc4b63bb13` |
| `src/video_manager/retime.py` | `ca443837b4b865871923d9a946f7264824e4d01275240d2d83f26de60a6d8ca9` |
| `src/video_manager/time_map.py` | `095268ff6bc975c94e430da8ade786f1b005cadea71b1d160cbcea402b8e92e6` |
| `src/video_manager/tools.py` | `4fc995a8645ec6664709582c0368e8ffe005228f35eb7dd336f65799dc4442b6` |
| `pyproject.toml` | `3c29cb7849f734f4842b3d8177542b19d221590a10be8e59faed750610fc6c9c` |
| `requirements-dev.txt` | `ba8a94ddb0dea8bc727be3a27f291ecd197398424ad567dd8c86a7e80334a9db` |
| `README.md` | `2a471f3ef0a339c1fdf352b90c692df7af1ec0bd3333ad2ef4bd0cecd2dfc004` |
| `examples/job.json` | `6283c045ec35069e0eb2ba7391fca0db7a191316ea25c0968109823d6f56c312` |
