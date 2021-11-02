# coding=utf-8
import datetime as dt
import json
import logging
import os
import pickle
import random
import time
import warnings
from telegram.error import NetworkError
import apiai
import facebook
import telegram
from environs import Env
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
)

warnings.filterwarnings("ignore", category=UserWarning)

env = Env()
env.read_env()

FACEBOOK_PAGE_ID = int(os.environ["FACEBOOK_PAGE_ID"])
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])
ADMIN_ID = env.list("ADMIN_ID")
FB_LIKE_ID = int(os.environ["FB_LIKE_ID"])

TELEGRAM_TOKEN = str(os.environ["TELEGRAM_TOKEN"])
FACEBOOK_TOKEN = str(os.environ["FACEBOOK_TOKEN"])

with open("bot_messages/help.txt", encoding="utf-8") as help_file:
    help_text = help_file.read()
with open("bot_messages/oath.txt", encoding="utf-8") as oath_file:
    oath_text = oath_file.read()
with open("bot_messages/nextday.txt", encoding="utf-8") as nextday_file:
    nextday = nextday_file.read().split("\n")
with open("bot_messages/sameday.txt", encoding="utf-8") as sameday_file:
    sameday = sameday_file.read().split("\n")
with open("bot_messages/links.txt", encoding="utf-8") as links_file:
    links_text = links_file.read()
with open("bot_messages/how.txt", encoding="utf-8") as how_file:
    how_text = how_file.read()

RECONNECT_INTERVAL = 5
FACEBOOK_TIME_DIFFERENCE = 3  # Local time ahead of Facebook time
UTC_TIME_DIFFERENCE = 3  # Local time ahead of UTC time
SERVER_TIME_DIFFERENCE = UTC_TIME_DIFFERENCE - int(
    dt.datetime.utcnow().astimezone().utcoffset().total_seconds() / 60 / 60
)  # Local time ahead of server time

NULLED_DATA_JSON = [
    [],
    {
        "Понедельник": [],
        "Вторник": [],
        "Среда": [],
        "Четверг": [],
        "Пятница": [],
        "Суббота": [],
        "Воскресенье": [],
    },
]
WEEKDAYS = tuple(NULLED_DATA_JSON[1].keys())  # For usability
TIMEOUT_TIME = 60  # timeout time for bot conversations
TIMEOUT = ConversationHandler.TIMEOUT
(
    SELECT_DAY,
    ASSIGN_MANAGERS,
    THANK_YOU,
    THANK_YOU_OPTOUT,
    SELECT_DAY_UNASSIGN,
    UNASSIGN_MANAGERS,
) = range(
    6
)  # conversation stages

remove_keyboard_markup = telegram.ReplyKeyboardRemove(remove_keyboard=True)

weekdays_buttons = [
    [telegram.KeyboardButton(i) for i in WEEKDAYS[:3]],
    [telegram.KeyboardButton(i) for i in WEEKDAYS[3:]],
]  # format of buttons
optin_buttons = [["Принимаю"], ["Отказываюся"]]
optin_buttons_captions = tuple(*zip(*optin_buttons))
optout_buttons = [["Потдверждаю отречение"], ["Это ошибка. Я с вами, ребята"]]
optout_buttons_captions = tuple(*zip(*optout_buttons))

sleep_counter = 0  # to make the bot speak less


def to_html(user):  # making a link out of a user_dict
    return (
        '<a href="tg://user?id=' + str(user["id"]) + '">' + user["first_name"] + "</a>"
    )


class PoliceBotData:  # singleton for the bot
    ASSOCIATED_FILENAME = "bot_data/chat_data.txt"

    def __init__(self, oathed_dict, assigned_dict):
        self.oathed = list(oathed_dict)
        self.assigned = assigned_dict
        try:
            (
                self.post_for_today,
                self.post_for_tomorrow,
                self.last_shared_fb_like,
            ) = pickle.load(open("bot_data/persistence.p", "rb"))
        except:
            self.post_for_today = False
            self.post_for_tomorrow = False
            self.last_shared_fb_like = []
            self.persistence()

    @classmethod
    def load(cls):  # loading chat data
        try:
            with open(cls.ASSOCIATED_FILENAME, "r", encoding="utf-8") as data_json:
                data = data_json.read()
            return cls(*json.loads(data))
        except FileNotFoundError:
            with open(cls.ASSOCIATED_FILENAME, "w", encoding="utf-8") as data_json:
                data_json.write(json.dumps(NULLED_DATA_JSON, ensure_ascii=False))
            return cls(*NULLED_DATA_JSON)

    def persistence(self):  # saving variables
        pickle.dump(
            (self.post_for_today, self.post_for_tomorrow, self.last_shared_fb_like),
            open("bot_data/persistence.p", "wb"),
        )

    def __len__(self):
        return len(self.oathed)

    def __getitem__(self, position):
        return self.oathed[position]

    def __str__(self):  # oathed  users as a string
        result_text = ""
        if len(self.oathed) == 0:
            result_text += "никого"
        else:
            for user in self.oathed:
                result_text += self.get_by_id(user["id"])["first_name"] + ", "
            result_text = result_text[:-2]
        return result_text

    def str_assigned(
        self, day, mentioning=False
    ):  # assigned users as a string (with mentioning)
        result_text = ""
        if len(self.assigned[day]) == 0:
            result_text += "никого"
        else:
            for user_id in self.assigned[day]:
                if mentioning:
                    result_text += to_html(self.get_by_id(user_id)) + ", "
                else:
                    result_text += self.get_by_id(user_id)["first_name"] + ", "
            result_text = result_text[:-2]
        return result_text

    def __contains__(self, user):
        for existing_user in self.oathed:
            if existing_user["id"] == user.id:
                return True
        return False

    def add_user(self, user):  # add someome who oathed
        if user.id not in (existing_user["id"] for existing_user in self.oathed):
            self.oathed.append(user.to_dict())

    def add_manager(self, day, user_id):  # assign a manager
        if self.get_by_id(user_id):
            if user_id not in self.assigned[day]:
                self.assigned[day].append(user_id)

    def remove_user(self, user_id):  # remove from oathed
        user_to_remove = self.get_by_id(user_id)
        if user_to_remove:
            self.oathed.remove(user_to_remove)
            for day in WEEKDAYS:
                try:
                    self.assigned[day].remove(user_id)
                except:
                    pass

    def unassign_manager(self, day, user_id):
        try:
            self.assigned[day].remove(user_id)
        except:
            pass

    def save(self):
        with open(self.ASSOCIATED_FILENAME, "w", encoding="utf-8") as data_json:
            data_json.write(
                json.dumps([self.oathed, self.assigned], ensure_ascii=False)
            )

    def get_by_id(self, user_id):
        for user in self.oathed:
            if user["id"] == user_id:
                return user
        return None

    def get_by_username(self, username):
        for user in self.oathed:
            try:
                if user["username"] == username:
                    return user
            except:
                pass
        return None


def selectivity(handler):
    """Talk to specific chats"""

    def i_dont_talk_to_you_bastard(update, context):
        print("New message from " + str(update.effective_chat.id))
        message_text = "Обратись к @KonnikPahoni, если тебе что-то от меня нужно."
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message_text,
            reply_to_message_id=update.message.message_id,
        )

    def decorated(update, context):
        print(update.message.chat.id)
        if int(update.message.chat.id) == TELEGRAM_CHAT_ID:
            return handler(update, context)
        elif int(update.message.chat.id) == FB_LIKE_ID:
            pass
        else:
            return i_dont_talk_to_you_bastard(update, context)

    return decorated


def admin_selectivity(handler):
    """Specific commands to bot admins only"""

    def i_dont_talk_to_you_bastard(update, context):
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Ты не похож(а) на главнокомандущего, бро :)",
            reply_to_message_id=update.message.message_id,
        )

    def decorated(update, context):
        condition = False
        try:
            condition = (str(update.message.from_user.id) in ADMIN_ID) and (
                int(update.message.chat.id) == TELEGRAM_CHAT_ID
            )
        except Exception:
            condition = (str(update.callback_query.from_user.id) in ADMIN_ID) and (
                int(update.callback_query.message.chat.id) == TELEGRAM_CHAT_ID
            )
        finally:
            if condition:
                return handler(update, context)
            else:
                return i_dont_talk_to_you_bastard(update, context)

    return decorated


@selectivity
def echo(update, context):  # sleep counter to make the bot talk less
    global sleep_counter
    if (update.message.reply_to_message.from_user.id == context.bot.id) or (
        context.bot.username in update.message.text
    ):
        if sleep_counter == 3:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="😴 Когда мной не командуют, я сплю. Тебе нужна /help?",
                reply_to_message_id=update.message.message_id,
            )
            sleep_counter = 0
        else:
            sleep_counter += 1


@selectivity
def help_command(update, context):
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@selectivity
def links_command(update, context):
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=links_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@selectivity
def how_command(update, context):
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=how_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@selectivity
def initiate_opting_in(update, context):
    if update.message.from_user in chat_data:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Второй раз принимать присягу не нужно ;)",
            reply_to_message_id=update.message.message_id,
        )
        return ConversationHandler.END
    else:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=oath_text,
            parse_mode="HTML",
            reply_to_message_id=update.message.message_id,
            reply_markup=telegram.ReplyKeyboardMarkup(
                optin_buttons,
                resize_keyboard=True,
                one_time_keyboard=True,
                selective=True,
            ),
        )
        return THANK_YOU


@selectivity
def thank_you(update, context):
    if update.message.text == optin_buttons_captions[0]:
        message_text = "Спасибо чувински. Семья тебя не забудет."
        chat_data.add_user(update.message.from_user)
        chat_data.save()
    else:
        message_text = "Ну как знаешь. Возможно, ты найдешь себя в другой роли."
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message_text,
        reply_to_message_id=update.message.message_id,
        reply_markup=remove_keyboard_markup,
    )
    return ConversationHandler.END


@selectivity
def initiate_opting_out(update, context):
    if update.message.from_user not in chat_data:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Чтобы отречься от медиаслужбы, сначала нужно принять присягу.",
            reply_to_message_id=update.message.message_id,
        )
        return ConversationHandler.END
    else:
        message_text = "Подтверди отречение от медиаслужбы. Мы простим."
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message_text,
            reply_markup=telegram.ReplyKeyboardMarkup(
                optout_buttons,
                resize_keyboard=True,
                one_time_keyboard=True,
                selective=True,
            ),
            reply_to_message_id=update.message.message_id,
        )
        return THANK_YOU_OPTOUT


@selectivity
def thank_you_optout(update, context):
    if update.message.text == optout_buttons[0][0]:
        message_text = (
            "Как знаешь. Возможно, ты найдешь себя в другой роли. Отречение принято."
        )
        chat_data.remove_user(update.message.from_user.id)
        chat_data.save()
    else:
        message_text = "Так-то лучше. Спасибо, что вы с нами."
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message_text,
        reply_to_message_id=update.message.message_id,
        reply_markup=remove_keyboard_markup,
    )
    return ConversationHandler.END


def invalid_answer_buttons(conversation_step):
    def callback(update, context):
        help_text = "Чтобы все было четко и на чилле, используй кнопки для ответа. Команда /cancel отменит операцию."
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=help_text,
            reply_to_message_id=update.message.message_id,
        )
        return conversation_step

    return callback


@selectivity
def routine(update, context):
    routine_text = "Распорядок постинга по дням недели:\n\n"
    for day in WEEKDAYS:
        routine_text += "<b>" + day + "</b>: " + chat_data.str_assigned(day) + "\n"
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=routine_text,
        reply_to_message_id=update.message.message_id,
        parse_mode="HTML",
    )


@selectivity
def oathed(update, context):
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Присягнувшие: " + str(chat_data),
        reply_to_message_id=update.message.message_id,
        parse_mode="HTML",
    )


@selectivity
def cancel(update, context):
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Все операции остановлены.",
        reply_markup=remove_keyboard_markup,
    )
    return ConversationHandler.END


@admin_selectivity
def initiate_assigning(update, context):
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="На какой день назначаем постера?",
        reply_markup=telegram.ReplyKeyboardMarkup(
            weekdays_buttons,
            resize_keyboard=True,
            one_time_keyboard=True,
            selective=True,
        ),
        reply_to_message_id=update.message.message_id,
    )
    return SELECT_DAY


@admin_selectivity
def initiate_unassigning(update, context):
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="С какого дня удаляем постера?",
        reply_markup=telegram.ReplyKeyboardMarkup(
            weekdays_buttons,
            resize_keyboard=True,
            one_time_keyboard=True,
            selective=True,
        ),
        reply_to_message_id=update.message.message_id,
    )
    return SELECT_DAY_UNASSIGN


@admin_selectivity
def select_day(update, context):
    global day
    day = update.message.text
    buttons = []
    for user in chat_data:
        if user["id"] not in chat_data.assigned[day]:
            if user["username"]:
                button_text = user["username"]
            else:
                button_text = user["first_name"]
            buttons.append(
                telegram.InlineKeyboardButton(
                    text=button_text, callback_data=str(user["id"])
                )
            )
    if len(buttons) != 0:
        inline_markup = telegram.InlineKeyboardMarkup(list(zip(buttons)))
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Выбери пользователя, которого нужно добавить на указанный день ("
            + day.lower()
            + ").",
            reply_markup=inline_markup,
            reply_to_message_id=update.message.message_id,
        )
        return ASSIGN_MANAGERS
    else:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Некого добавить на этот день. Операция завершена.",
            reply_to_message_id=update.message.message_id,
            reply_markup=remove_keyboard_markup,
        )
        return ConversationHandler.END


@admin_selectivity
def select_day_unassign(update, context):
    global day
    day = update.message.text
    if len(chat_data.assigned[day]) != 0:
        buttons = []
        for user_id in chat_data.assigned[day]:
            user = chat_data.get_by_id(user_id)
            if user["username"]:
                button_text = user["username"]
            else:
                button_text = user["first_name"]
            buttons.append(
                telegram.InlineKeyboardButton(
                    text=button_text, callback_data=str(user["id"])
                )
            )
        inline_markup = telegram.InlineKeyboardMarkup(list(zip(buttons)))
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Выбери пользователя, которого нужно удалить с указанного дня ("
            + day.lower()
            + ").",
            reply_markup=inline_markup,
            reply_to_message_id=update.message.message_id,
        )
        return UNASSIGN_MANAGERS
    else:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Некого удалить с этого дня. Операция завершена.",
            reply_to_message_id=update.message.message_id,
            reply_markup=remove_keyboard_markup,
        )
        return ConversationHandler.END


@admin_selectivity
def assign_manager(update, context):
    selected_user = chat_data.get_by_id(int(update.callback_query.data))
    chat_data.add_manager(day, selected_user["id"])
    response_text = to_html(selected_user) + " внесен в распорядок."
    chat_data.save()
    context.bot.edit_message_text(
        chat_id=update.callback_query.message.chat_id,
        message_id=update.callback_query.message.message_id,
        text=response_text,
        parse_mode="HTML",
    )
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Операция завершена.",
        reply_markup=remove_keyboard_markup,
        reply_to_message_id=update.callback_query.message.message_id,
    )
    return ConversationHandler.END


def unassign_manager(update, context):
    selected_user = chat_data.get_by_id(int(update.callback_query.data))
    chat_data.unassign_manager(day, selected_user["id"])
    response_text = to_html(selected_user) + " удален из распорядка."
    chat_data.save()
    context.bot.edit_message_text(
        chat_id=update.callback_query.message.chat_id,
        message_id=update.callback_query.message.message_id,
        text=response_text,
        parse_mode="HTML",
    )
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Операция завершена.",
        reply_markup=remove_keyboard_markup,
        reply_to_message_id=update.callback_query.message.message_id,
    )
    return ConversationHandler.END


def localize(server_datetime):
    """Server datetime to local datetime"""
    return server_datetime + dt.timedelta(hours=SERVER_TIME_DIFFERENCE)


def localize_facebook(facebook_datetime):
    """Facebook datetime to local datetime"""
    return facebook_datetime + dt.timedelta(hours=FACEBOOK_TIME_DIFFERENCE)


def serverize(local_datetime):
    """Local datetime to server datetime"""
    return local_datetime - dt.timedelta(hours=SERVER_TIME_DIFFERENCE)


def message(post_data):  # appears 2 times later
    try:
        result_message = post_data["message"]
    except:
        result_message = "*в посте нет текста*"
    return result_message


def localised_post_datetime(fb_post_datetime):
    """Localize_facebook applied to fb iso format"""
    return localize_facebook(dt.datetime.fromisoformat(fb_post_datetime[:19]))


def get_scheduled_posts(days_from_today, include_all=False):
    result = []
    selection_date = localize(dt.datetime.today()).date() + dt.timedelta(
        days=days_from_today
    )
    posts = graph.get_object(id=str(FACEBOOK_PAGE_ID) + "/scheduled_posts")
    for post_data in posts["data"]:
        post_datetime = localize(
            dt.datetime.fromtimestamp(
                graph.get_object(id=post_data["id"], fields="scheduled_publish_time")[
                    "scheduled_publish_time"
                ]
            )
        )
        if (include_all and post_datetime.date() <= selection_date) or (
            post_datetime.date() == selection_date
        ):
            result.append(
                {
                    "created_time": post_datetime,
                    "message": message(post_data),
                    "id": int(post_data["id"].split("_")[1]),
                }
            )
    return sorted(result, key=lambda x: x["created_time"])


@selectivity
def scheduled_posts(update, context):
    """Show scheduled posts"""
    while True:
        try:
            scheduled = get_scheduled_posts(360, include_all=True)
            break
        except Exception:
            print("Could not get scheduled posts. Retrying")
            time.sleep(RECONNECT_INTERVAL)

    if scheduled:
        message_text = "Поставленные в очередь посты:\n\n"
        for post in scheduled:
            link = "https://facebook.com/LegalizeBelarus/posts/" + str(post["id"]) + "/"
            message_text += (
                '<a href="'
                + link
                + '">'
                + str(post["created_time"])
                + "</a>:\n\n<i>"
                + post["message"]
                + "</i>\n\n"
            )
    else:
        message_text = "В очереди нет постов!"
    context.bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=message_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


def get_published_posts(get_all=False):
    result = []
    posts = graph.get_object(id=str(FACEBOOK_PAGE_ID) + "/posts")
    for post_data in posts["data"]:
        post_datetime = localised_post_datetime(post_data["created_time"])
        if post_datetime.date() == localize(dt.datetime.today()).date() or get_all:
            result.append(
                {
                    "created_time": post_datetime,
                    "message": message(post_data),
                    "id": int(post_data["id"].split("_")[1]),
                }
            )
    return result


@selectivity
def published_posts(update, context):
    """Show published posts"""
    message_text = "Последний пост на странице:\n\n"

    while True:
        try:
            post = get_published_posts(get_all=True)[0]
            break
        except Exception:
            print("Could not get published posts. Retrying")
            time.sleep(RECONNECT_INTERVAL)

    link = "https://facebook.com/LegalizeBelarus/posts/" + str(post["id"]) + "/"
    message_text += (
        '<a href="'
        + link
        + '">'
        + str(post["created_time"])
        + "</a>:\n\n<i>"
        + post["message"]
        + "</i>\n\n"
    )
    context.bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=message_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


def sameday_checker(context):
    if not chat_data.post_for_today:

        while True:
            try:
                scheduled = get_scheduled_posts(0)
                break
            except Exception:
                print("Could not get scheduled posts. Retrying")
                time.sleep(RECONNECT_INTERVAL)

        while True:
            try:
                posted = get_published_posts()
                break
            except Exception:
                print("Could not get published posts. Retrying")
                time.sleep(RECONNECT_INTERVAL)

        week_day = WEEKDAYS[localize(dt.datetime.today()).weekday()]
        if scheduled:
            message_text = "<b>На сегодня пост стоит!</b>\n\n"
            chat_data.post_for_today = True
            chat_data.persistence()
            for post in scheduled:
                link = (
                    "https://facebook.com/LegalizeBelarus/posts/"
                    + str(post["id"])
                    + "/"
                )
                message_text += (
                    '<a href="'
                    + link
                    + '">'
                    + str(post["created_time"])
                    + "</a>:\n\n<i>"
                    + post["message"]
                    + "</i>\n\n"
                )
            if chat_data.assigned[week_day]:
                message_text += (
                    "<b>Спасибо, " + chat_data.str_assigned(week_day) + "</b>"
                )
        elif posted:
            message_text = "<b>Сегодня пост запощен!</b>\n\n"
            chat_data.post_for_today = True
            chat_data.persistence()
            for post in posted:
                link = (
                    "https://facebook.com/LegalizeBelarus/posts/"
                    + str(post["id"])
                    + "/"
                )
                message_text += (
                    '<a href="'
                    + link
                    + '">'
                    + str(post["created_time"])
                    + "</a>:\n\n<i>"
                    + post["message"]
                    + "</i>\n\n"
                )
            if chat_data.assigned[week_day]:
                message_text += (
                    "<b>Спасибо, " + chat_data.str_assigned(week_day) + "</b>"
                )
        else:
            message_text = "Поста на сегодня нет! Кто-нибудь может сделать?"
            if chat_data.assigned[week_day]:
                message_text = random.choice(sameday).replace(
                    "#", chat_data.str_assigned(week_day, mentioning=True)
                )

        context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


def nextday_checker(context):
    if not chat_data.post_for_tomorrow:

        while True:
            try:
                scheduled = get_scheduled_posts(1)
                break
            except Exception:
                print("Could not get scheduled posts. Retrying")
                time.sleep(RECONNECT_INTERVAL)

        week_day = WEEKDAYS[(localize(dt.datetime.today()).weekday() + 1) % 7]
        if scheduled:
            message_text = "<b>На завтра пост стоит!</b>\n\n"
            chat_data.post_for_tomorrow = True
            chat_data.persistence()
            for post in scheduled:
                link = (
                    "https://facebook.com/LegalizeBelarus/posts/"
                    + str(post["id"])
                    + "/"
                )
                message_text += (
                    '<a href="'
                    + link
                    + '">'
                    + str(post["created_time"])
                    + "</a>:\n\n<i>"
                    + post["message"]
                    + "</i>\n\n"
                )
            if chat_data.assigned[week_day]:
                message_text += (
                    "<b>Спасибо, " + chat_data.str_assigned(week_day) + "</b>"
                )
        else:
            message_text = "Поста на завтра не стоит. Кто-нибудь сможет сделать? Просто интересуюсь."
            if chat_data.assigned[week_day]:
                message_text = random.choice(nextday).replace(
                    "#", chat_data.str_assigned(week_day, mentioning=True)
                )
        context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


def evening_nuller(context):
    week_day = WEEKDAYS[localize(dt.datetime.today()).weekday()]
    if not chat_data.post_for_today:
        message_text = "Сегодня пост не был запощен..."
        if chat_data.assigned[week_day]:
            message_text += (
                " "
                + chat_data.str_assigned(week_day, mentioning=True)
                + ", как тебе не стыдно!"
            )
        context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


def night_nuller(context):  # where tomorrow becomes today
    global sleep_counter
    sleep_counter = 0
    chat_data.post_for_today = False
    if chat_data.post_for_tomorrow:
        chat_data.post_for_today = True
        chat_data.post_for_tomorrow = False
    chat_data.persistence()


def fb_like_checker(context):
    def send_message(chat_id):
        context.bot.send_message(
            chat_id=chat_id,
            text="Сябры, дапаможам легалайзу лайкамі! Загядзя дзякуй!\n" + message_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    while True:
        try:
            _published = get_published_posts(get_all=True)
            break
        except Exception as e:
            print(f"Could not get published posts. {str(e)} Retrying")
            time.sleep(RECONNECT_INTERVAL)

    published = [post["id"] for post in _published][:5]
    message_text = ""

    if published[0] not in chat_data.last_shared_fb_like:
        link = "https://facebook.com/LegalizeBelarus/posts/" + str(published[0])
        message_text += link

    if message_text != "":
        chat_data.post_for_today = True
        send_message(FB_LIKE_ID)
        chat_data.last_shared_fb_like = published
        chat_data.persistence()


updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
graph = facebook.GraphAPI(access_token=FACEBOOK_TOKEN, version="3.1")

job_queue = updater.job_queue

job_queue.run_daily(night_nuller, dt.time(hour=5 - UTC_TIME_DIFFERENCE, minute=0))
job_queue.run_daily(sameday_checker, dt.time(hour=17 - UTC_TIME_DIFFERENCE, minute=0))
job_queue.run_daily(sameday_checker, dt.time(hour=18 - UTC_TIME_DIFFERENCE, minute=0))
job_queue.run_daily(sameday_checker, dt.time(hour=19 - UTC_TIME_DIFFERENCE, minute=0))
job_queue.run_daily(sameday_checker, dt.time(hour=20 - UTC_TIME_DIFFERENCE, minute=0))
job_queue.run_daily(evening_nuller, dt.time(hour=21 - UTC_TIME_DIFFERENCE, minute=0))
job_queue.run_repeating(fb_like_checker, 120, first=1)

dispatcher = updater.dispatcher

cancel_handler = CommandHandler("cancel", cancel)

assign_handler = ConversationHandler(
    entry_points=[CommandHandler("assign", initiate_assigning)],
    states={
        SELECT_DAY: [
            MessageHandler(Filters.text(WEEKDAYS), select_day),
            cancel_handler,
            MessageHandler(Filters.all, invalid_answer_buttons(SELECT_DAY)),
        ],
        ASSIGN_MANAGERS: [CallbackQueryHandler(assign_manager), cancel_handler],
        TIMEOUT: [MessageHandler(Filters.all, cancel)],
    },
    fallbacks=[],
    conversation_timeout=TIMEOUT_TIME,
)

unassign_handler = ConversationHandler(
    entry_points=[CommandHandler("unassign", initiate_unassigning)],
    states={
        SELECT_DAY_UNASSIGN: [
            MessageHandler(Filters.text(WEEKDAYS), select_day_unassign),
            cancel_handler,
            MessageHandler(Filters.all, invalid_answer_buttons(SELECT_DAY_UNASSIGN)),
        ],
        UNASSIGN_MANAGERS: [CallbackQueryHandler(unassign_manager)],
        TIMEOUT: [MessageHandler(Filters.all, cancel)],
    },
    fallbacks=[],
    conversation_timeout=TIMEOUT_TIME,
)

optin_handler = ConversationHandler(
    entry_points=[CommandHandler("optin", initiate_opting_in)],
    states={
        THANK_YOU: [MessageHandler(Filters.text(optin_buttons_captions), thank_you)],
        TIMEOUT: [MessageHandler(Filters.all, cancel)],
    },
    fallbacks=[
        cancel_handler,
        MessageHandler(Filters.all, invalid_answer_buttons(THANK_YOU)),
    ],
    conversation_timeout=TIMEOUT_TIME,
)

optout_handler = ConversationHandler(
    entry_points=[CommandHandler("optout", initiate_opting_out)],
    states={
        THANK_YOU_OPTOUT: [
            MessageHandler(Filters.text(optout_buttons_captions), thank_you_optout)
        ],
        TIMEOUT: [MessageHandler(Filters.all, cancel)],
    },
    fallbacks=[
        cancel_handler,
        MessageHandler(Filters.all, invalid_answer_buttons(THANK_YOU)),
    ],
    conversation_timeout=TIMEOUT_TIME,
)

dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("links", links_command))
dispatcher.add_handler(CommandHandler("how", how_command))
dispatcher.add_handler(CommandHandler("routine", routine))
dispatcher.add_handler(CommandHandler("oathed", oathed))
dispatcher.add_handler(CommandHandler("scheduled", scheduled_posts))
dispatcher.add_handler(CommandHandler("published", published_posts))
dispatcher.add_handler(assign_handler)
dispatcher.add_handler(unassign_handler)
dispatcher.add_handler(optin_handler)
dispatcher.add_handler(optout_handler)
dispatcher.add_handler(cancel_handler)
dispatcher.add_handler(MessageHandler(Filters.all, echo))

chat_data = PoliceBotData.load()

print("Media Police Bot started")

while True:
    try:
        updater.start_polling()
    except NetworkError as e:
        print("Network error. Reconnecting in " + str(RECONNECT_INTERVAL) + " seconds")
        time.sleep(RECONNECT_INTERVAL)
