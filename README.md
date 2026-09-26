# TradeRail Desktop Releases

This repository also publishes `market_calendar.v1.json`, the validated
offline-first exchange schedule consumed by TradeRail Relay. A weekly workflow
generates it with the latest compatible `exchange-calendars` 4.x release,
rejects coverage regressions, and commits the candidate only after a second
validation in a separate write-enabled job.

TradeRail 데스크톱 앱의 공식 공개 배포 채널입니다.

설치 파일과 앱 내부 업데이트 파일은 [Releases](https://github.com/jeongu-97/TradeRail-Desktop-Releases/releases)에서 제공합니다. 배포 파일은 비공개 소스 저장소의 릴리스 자동화에서 빌드·검증한 뒤 이 저장소에 게시합니다.

## 배포 파일

- macOS `.dmg`: 최초 설치
- macOS `.zip`: 앱 내부 업데이트
- Windows `setup.exe`: 최초 설치
- Windows `.zip`: 앱 내부 업데이트

이 저장소에는 TradeRail 소스코드, 서명 개인키, 인증 토큰 또는 사용자 데이터가 포함되지 않습니다.

공식 서비스: [traderail.app](https://traderail.app)
