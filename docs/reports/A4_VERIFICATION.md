# A4 독립 검증 보고서

판정: **합성 기술 검증 통과 / 실제 영상 품질 검증 대기**.

구현 담당과 별도 검증 작업자가 고정된 제품 코드 및 A4 실행기를 검사했다. 제품 수정·커밋·푸시 없음. 작업 B는 시작하지 않았다.

## 최종 회귀 검사

| 독립 재실행 명령 | 결과 |
| --- | --- |
| `.venv/bin/python -m unittest discover -s tests/unit -v` | 7 통과 |
| `.venv/bin/python -m unittest discover -s tests/integration -v` | 8 통과 |
| `.venv/bin/python -m unittest discover -s tests/verification -v` | 9 통과 |

총 24개 통과, 실패·건너뜀 없음. 기존 개별 단계 검증 후 CLI·의존성·실행 안내가 확장되어 최종 상태에서 한 번 전체 회귀 검사를 수행했다.

## A4 산출물 독립 검사

대상: `outputs/a4-demo/manifest.json`, `outputs/a4-demo/REVIEW.md`, normal/stress 각 4클립 및 5개 CLI 작업의 출력.

- 원본 8개, 보고서 5개, 출력 영상 65개의 SHA256을 manifest와 대조하여 일치 확인.
- 제품 probe 대신 직접 ffprobe `-count_frames`로 출력 65개 전체의 디코딩 프레임 수·길이를 manifest와 대조하여 일치 확인.
- `normal_off`, `stress_off`의 기준본과 후보를 독립 FFmpeg RGB 디코딩하여 모든 픽셀 동일함 확인.
- `stress_on`의 보정본 모든 프레임을 보고서 지정 원본 프레임 픽셀과 대조, 평균 오차 4 미만 확인. 속도 차이 구간 실제 프레임 스케줄 변경, 방향 반전 속도 보정 억제, 정지·불일치 경계 속도 보정 및 중복 제거 억제 확인.
- `normal_clip2_disabled`의 양쪽 인접 경계 보정 억제 및 클립 2의 0~39 프레임 유지 확인.
- 24개 회귀 검사에서 F1 프레임 식별·VFR/비영 PTS, F2 비교 시계와 실제 픽셀, F3 제외 조합, 원본·기존 결과 보호를 추가로 재확인.

검사 실행은 `/tmp/verify_a4_artifacts.py`로 수행했고 재사용 가능한 동일 검사 본문을 `tests/verification/verify_a4_artifacts.py`에 보관했다. 재실행: `.venv/bin/python tests/verification/verify_a4_artifacts.py` (A4 데모 산출물 필요).

manifest SHA256: `a93a38a94a60bdbd7a2546b18f86ac5dc97435173032123ea80aa3eeffb9a855`.

## 실제 품질 및 진행 게이트

합성 결과는 기술적 기능 검증이다. 실제 생성 영상에서 꿀렁임이 개선되는지 정상 속도로 사람이 판단한 결과가 아니다. 실제 순서가 있는 3~4개 클립과 사용자 비교·품질 확인이 필요하다. 따라서 A4 전체는 실제 품질 검증 대기이며 B·C·D는 진행하지 않는다.

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
| `README.md` | `df63a946dcf3106a8c79fcf3402393551a55cbc709f65b423bd8ba47979fa51a` |
| `tests/fixtures/run_a4_demo.py` | `772edd5d8310912bca519562e8f9631eb31db88a19c3af2f0fcfe9f02f34b26d` |
| `tests/fixtures/synthetic.py` | `54e7a247253c60e636b7e4c88eea5779c9548e6c6d7d950edba622b90b21e38f` |
