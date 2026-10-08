> **Основной репозиторий этого проекта — https://code.pecheny.me/pecheny/chgksuite, пожалуйста, создавайте issues там.**

<img src="icon.png" width="256" />

# chgksuite

Система для работы с пакетами ЧГК.

Документация: https://chgksuite.pecheny.me

Последняя версия в релизах: https://code.pecheny.me/pecheny/chgksuite/releases
## Разработка

Пушьте только в Forgejo (`origin`, code.pecheny.me). GitHub — зеркало, оно синхронизируется с Forgejo автоматически, поэтому пушить в него напрямую не нужно. Сборки запускает `.github/workflows/build.yml` на GitHub: на macOS он подписывает приложения сертификатом Developer ID и нотаризует их. Сертификат и ключ App Store Connect лежат в секретах Actions репозитория на GitHub.
