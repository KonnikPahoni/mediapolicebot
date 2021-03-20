@media_police_bot — это бот для командного постинга в Facebook. Будет полезен организациям, которым необходимо организовать поочередный постинг в социальных сетях.

### Getting tokens

1. Создайте бота через [@BotFather](http://t.me/BotFather "@BotFather"). Описания команд находятся в файле BotFather.txt
2. Создайте приложение в Facebook и получите long-lived User access token и [сгенерируйте Page access token with no expiration date](https://developers.facebook.com/docs/pages/access-tokens/ "сгенерируйте Page access token with no expiration date")
3. Получите токен DialogFlow и [создайте агента](https://habr.com/ru/post/346606/ "создайте агента")

###### Конфигурация:

FACEBOOK_PAGE_ID (страница, на которой происходит постинг)
TELEGRAM_CHAT_ID (рабочий чатик группы тех, кто постит)
ADMIN_ID (Telegram id администраторов бота)
FB_LIKE_ID (группа для *ЛАЙК-АТАК*)

### Dependencies:

facebook-sdk==3.1.0
python-telegram-bot==12.4.2
apiai==1.2.3
numpy==1.18.1
environs==9.3.1