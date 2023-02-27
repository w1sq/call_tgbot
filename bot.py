import datetime
import typing
import aiofiles
import aiogram
from config import Config
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from db.storage import UserStorage, User
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import aioschedule


class GetAnswer(StatesGroup):
    answer_paid_id = State()
    answer_limit = State()
    answer_unpaid_id = State()
    phone_number = State()


class TG_Bot():
    def __init__(self, user_storage: UserStorage):
        self._user_storage:UserStorage = user_storage
        self._bot:aiogram.Bot = aiogram.Bot(token=Config.TGBOT_API_KEY)
        self._storage:MemoryStorage = MemoryStorage()
        self._dispatcher:aiogram.Dispatcher = aiogram.Dispatcher(self._bot, storage=self._storage)
        self.patterns = ['Ошибка недостаточно денежных средств']
    
    async def start(self):
        print('Bot has started')
        await self._dispatcher.start_polling()
    
    def init(self) :
        aioschedule.every().minute.do(self._check_subscriptions)
        self._init_handler()
    
    def _generate_back_keyb(self):
        return InlineKeyboardMarkup().add(InlineKeyboardButton(text='Назад', callback_data='cancel'))

    def _generate_pattern_keyb(self):
        pattern_keyb = InlineKeyboardMarkup()
        for id in range(len(self.patterns)):
            pattern_keyb.add(InlineKeyboardButton(text=str(id+1)+'. '+self.patterns[id], callback_data='send_request '+str(id)))
        pattern_keyb.add(InlineKeyboardButton(text='Отмена',callback_data='cancel'))
        return pattern_keyb

    def _generate_menu_keyb(self, user:User):
        match user.role:
            case User.USER:
                return ReplyKeyboardMarkup(resize_keyboard=True)\
                    .row(KeyboardButton('👤 Мой аккаунт'))
            case User.PAID:
                return ReplyKeyboardMarkup(resize_keyboard=True)\
                    .row(KeyboardButton('📞 Позвонить'), KeyboardButton('👤 Мой аккаунт'))
            case User.ADMIN:
                return ReplyKeyboardMarkup(resize_keyboard=True)\
                    .row(KeyboardButton('📞 Позвонить'), KeyboardButton('👤 Мой аккаунт'))\
                        .row(KeyboardButton('Добавить подписку'), KeyboardButton('Убрать подписку'))\
                            .row(KeyboardButton("Добавить шаблон"))

    async def _show_menu(self, message:aiogram.types.Message , user:User):
        local_keyb = self._generate_menu_keyb(user)
        await message.answer('Добро пожаловать в меню\nВыберите интересующий вас пункт навигации:', reply_markup=local_keyb)

    async def _get_profile_info(self, message:aiogram.types.Message, user:User):
        answer_text = f"👤 Ваш профиль:\n\n├ ID: `{user.id}`\n├ Ваш никнейм: `{message['from']['username']}`\n├ Ваше имя: `{message['from']['first_name']}`"
        match user.role:
            case User.USER:
                answer_text += f"\n├ Подписка отсутсвует"
            case User.PAID:
                answer_text += f"\n├ Подписка до: {user.expire_date.strftime('%d-%m-%Y')}\n├ Количество звонков: {user.calls}"
        await message.answer(answer_text, parse_mode=aiogram.types.ParseMode.MARKDOWN)

    async def _make_call(self, message:aiogram.types.Message, user:User):
        await message.answer('Введите номер в формате: +7999 или 8999', reply_markup=self._generate_back_keyb())
        await GetAnswer.phone_number.set()

    async def _choose_pattern(self, message:aiogram.types.Message, state:aiogram.dispatcher.FSMContext):
        user = await self._user_storage.get_by_id(message.chat.id)
        if user and (user.role == User.ADMIN or user.role == User.PAID and user.calls>0) and (message.text.isdigit() and len(message.text) == 11 or message.text[1:].isdigit() and len(message.text) == 12):
            await message.answer('Выберите шаблон:', reply_markup=self._generate_pattern_keyb())
            await state.update_data(number=message.text)
        else:
            await message.answer('Неверный формат ввода номера телефона, попробуйте снова', reply_markup=self._generate_back_keyb())

    async def _send_request(self, call:aiogram.types.CallbackQuery):
        pattern_id = int(call.data.split()[1])
        state = self._dispatcher.current_state()
        state_data = await state.get_data()
        await state.finish()
        await call.message.answer(f'Пробую позвонить на номер {state_data["number"]} с шаблоном {self.patterns[pattern_id]}')

    async def _ask_unpaid_id(self, message:aiogram.types.Message, user:User):
        await message.answer('Пришлите id пользователя, у которого хотите забрать доступ, ОТМЕНА для отмены')
        await GetAnswer.answer_unpaid_id.set()

    async def _set_unpaid_id(self, message:aiogram.types.Message, state:aiogram.dispatcher.FSMContext):
        if message.text == "ОТМЕНА":
            await message.answer('Успешно отменено')
        elif message.text.isdigit():
            db_user = await self._user_storage.get_by_id(int(message.text))
            if db_user is not None:
                if db_user.role == User.BLOCKED:
                    await message.answer('Пользователь заблокирован')
                if db_user.role == User.PAID:
                    await self._user_storage.remove_paid(db_user)
                    local_keyb = self._generate_menu_keyb(db_user)
                    await self._bot.send_message(chat_id=db_user.id, text="Ваш доступ был аннулирован.", reply_markup=local_keyb)
                    await message.answer('У пользователя больше нет подписки')
                else:
                    await message.answer('У пользователя и так нет подписки')
            else:
                await message.answer('Такого пользователя не найдено')
        else:
            await message.answer('Неправильный формат')
        await state.finish()

    async def _ask_paid_id(self, message:aiogram.types.Message, user:User):
        await message.answer('Пришлите id оплатившего пользователя, ОТМЕНА для отмены')
        await GetAnswer.answer_paid_id.set()
    
    async def _set_paid_id(self, message:aiogram.types.Message, state:aiogram.dispatcher.FSMContext):
        if message.text == "ОТМЕНА":
            await message.answer('Успешно отменено.')
        elif message.text.isdigit():
            db_user = await self._user_storage.get_by_id(int(message.text))
            if db_user is not None:
                if db_user.role == User.BLOCKED:
                    await message.answer('Пользователь заблокирован')
                if db_user.role != User.PAID:
                    await self._user_storage.add_paid(db_user)
                    local_keyb = ReplyKeyboardMarkup(resize_keyboard=True).row(KeyboardButton('📞 Позвонить'), KeyboardButton('👤 Мой аккаунт'))
                    await self._bot.send_message(chat_id=db_user.id, text="Теперь у вас есть подписка", reply_markup=local_keyb)
                    # await self._bot.send_message(chat_id=Config.admins_chat_id, text=f'Пользователю с ID {db_user.id} был выдан доступ администратором с ID {message.chat.id}.')
                    await message.answer('Пользователь успешно добавлен')
                else:
                    await message.answer('У пользователя и так есть подписка')
            else:
                await message.answer('Такого пользователя не найдено')
        else:
            await message.answer('Неправильный формат')
        await state.finish()

    # async def _access_users_list(self, message:aiogram.types.Message, user:User):
    #     users = await self._user_storage.get_role_list(User.PAID)
    #     if users is None or len(users) == 0:
    #         await message.answer('Людей с подпиской нет')
    #     else:
    #         users = map(lambda x:str(x), users)
    #         async with aiofiles.open('paid_users.txt', 'w') as f:
    #             await f.write("\n".join(users))
    #         async with aiofiles.open('paid_users.txt', 'rb') as f:
    #             await message.answer_document(f)

    async def _users_amount(self, message:aiogram.types.Message, user:User):
        users = await self._user_storage.get_user_amount()
        await message.answer(f'Количество пользователей: {users}')

    # async def _increase_limits(self, message:aiogram.types.Message, user:User):
    #     await message.answer('Пришлите id пользователя и изменение его лимита через пробел')
    #     await GetAnswer.answer_limit.set()
    
    # async def _update_user_limit(self, message:aiogram.types.Message, state:aiogram.dispatcher.FSMContext):
    #     user_id, limit_delta = map(lambda x: int(x), message.text.split())
    #     user = await self._user_storage.get_by_id(user_id)
    #     if user is None:
    #         await message.answer('Пользователь с таким id не найден')
    #     elif user.role == User.BLOCKED:
    #         await message.answer('Пользователь заблокирован, выдача лимитов ему бесполезна')
    #     else:
    #         await self._user_storage.change_phrase_limit(user, limit_delta)
    #         await message.answer(f'Лимит пользователя с id {user_id} успешно изменен на {limit_delta}')
    #     await state.finish()

    # async def _promote_to_admin(self, message:aiogram.types.Message, user:User):
    #     admin_id = message.text.split()[1]
    #     user = await self._user_storage.get_by_id(int(admin_id))
    #     if user is not None:
    #         if user.role in (User.ADMIN, User.BLOCKED):
    #             match user.role:
    #                 case User.ADMIN:
    #                     await message.answer('Пользователь уже админ')
    #                 case User.BLOCKED:
    #                     await message.answer('Пользователь заблокирован')
    #         else:
    #             await self._user_storage.promote_to_admin(int(admin_id))
    #             await message.answer(f'Роль администратора выдана по id {admin_id}')
    #     else:
    #         await message.answer(f'Пользователя с id {admin_id} не найдено')
    
    # async def _demote_from_admin(self, message:aiogram.types.Message, user:User):
    #     admin_id = message.text.split()[1]
    #     user = await self._user_storage.get_by_id(int(admin_id))
    #     if user is not None:
    #         if user.role == User.ADMIN:
    #             await self._user_storage.demote_from_admin(int(admin_id))
    #             await message.answer(f'Пользователь {admin_id} больше не администратор.')
    #         else:
    #             await message.answer(f'Пользователь {admin_id} и так не админ.')
    #     else:
    #         await message.answer(f'Пользователя с id {admin_id} не найдено')

    # async def _ban_user(self, message:aiogram.types.Message, user:User):
    #     user_id = message.text.split()[1]
    #     user = await self._user_storage.get_by_id(int(user_id))
    #     if user is not None:
    #         if user.role != User.BLOCKED:
    #             await self._user_storage.ban_user(int(user_id))
    #             await message.answer('Пользователь заблокирован')
    #             await self._bot.send_message(chat_id=user_id, text='Ваш аккаунт был заблокирован')
    #         else:
    #             await message.answer('Пользователь и так заблокирован')
    #     else:
    #         await message.answer(f'Пользователя с id {user_id} не найдено')
    
    # async def _unban_user(self, message:aiogram.types.Message, user:User):
    #     user_id = message.text.split()[1]
    #     user = await self._user_storage.get_by_id(int(user_id))
    #     if user is not None:
    #         if user.role == User.BLOCKED:
    #             await self._user_storage.unban_user(int(user_id))
    #             await message.answer(f'Пользователь {user_id} разблокирован.')
    #             await self._bot.send_message(chat_id=user_id, text='Ваш аккаунт был разблокирован')
    #         else:
    #             await message.answer(f'Пользователь {user_id} и так не заблокирован.')
    #     else:
    #         await message.answer(f'Пользователя с id {user_id} не найдено')

    def _init_handler(self):
        self._dispatcher.register_callback_query_handler(self._send_request, aiogram.dispatcher.filters.Text(startswith="send_request "), state="*")
        # self._dispatcher.register_callback_query_handler(self._deny_payment, aiogram.dispatcher.filters.Text(startswith="deny "))
        # self._dispatcher.register_callback_query_handler(self._approve_payment, aiogram.dispatcher.filters.Text(startswith="approve "))
        # self._dispatcher.register_message_handler(self._user_middleware(self._god_required(self._ban_user)), commands=['ban'])
        # self._dispatcher.register_message_handler(self._user_middleware(self._god_required(self._unban_user)), commands=['unban'])
        # self._dispatcher.register_message_handler(self._user_middleware(self._god_required(self._demote_from_admin)), commands=['remove_admin'])
        # self._dispatcher.register_message_handler(self._user_middleware(self._god_required(self._promote_to_admin)), commands=['add_admin'])
        # self._dispatcher.register_message_handler(self._user_middleware(self._admin_required(self._add_phrase)), commands=['phrase'])
        # self._dispatcher.register_message_handler(self._user_middleware(self._admin_required(self._add_phrases)), commands=['phrases'])
        # self._dispatcher.register_message_handler(self._user_middleware(self._admin_required(self._phrases_amount)), commands=['phrase_amount'])
        self._dispatcher.register_message_handler(self._user_middleware(self._show_menu), commands=['start', 'menu'])
        # self._dispatcher.register_message_handler(self._user_middleware(self._show_menu), text='↘️ Пропустить')
        # self._dispatcher.register_message_handler(self._user_middleware(self._worked_out_reviews), text='✅ Я изучил отзывы')
        # self._dispatcher.register_message_handler(self._user_middleware(self._will_think), text='↘️ Ещё подумаю')
        # self._dispatcher.register_message_handler(self._user_middleware(self._show_menu), text='Меню')
        # self._dispatcher.register_message_handler(self._user_middleware(self._check_subscription), text='✅ Проверить подписку')
        # self._dispatcher.register_message_handler(self._user_middleware(self._start_education), text='✨Начать обучение')
        # self._dispatcher.register_message_handler(self._user_middleware(self._start_education), text='✒️ Обучение')
        # self._dispatcher.register_message_handler(self._user_middleware(self._paid_required(self._start_paid_education)), text='✒️ Начать обучение')
        # self._dispatcher.register_message_handler(self._user_middleware(self._paid_required(self._step1_paid_education)), text='WINDOWS')
        # self._dispatcher.register_message_handler(self._user_middleware(self._paid_required(self._step2_paid_education)), text='⤵️ Я скачал и установил Python')
        # self._dispatcher.register_message_handler(self._user_middleware(self._paid_required(self._step3_paid_education)), text='⤵️ Я скачал и установил библиотеку')
        # self._dispatcher.register_message_handler(self._user_middleware(self._paid_required(self._step4_paid_education)), text='⤵️ Я скачал программу')
        # self._dispatcher.register_message_handler(self._user_middleware(self._paid_required(self._step5_paid_education)), text='⤵️ Я скачал базу данных')
        # self._dispatcher.register_message_handler(self._user_middleware(self._paid_required(self._step6_paid_education)), text='✅ Завершить обучение')
        # self._dispatcher.register_message_handler(self._user_middleware(self._step2_education), text='⤵️ Шаг 1')
        # self._dispatcher.register_message_handler(self._user_middleware(self._step3_education), text='⤵️ Я создал кошелёк')
        # self._dispatcher.register_message_handler(self._user_middleware(self._step4_education), text='✨ Сгенерировать фразу')
        # self._dispatcher.register_message_handler(self._user_middleware(self._step5_education), text='✅ Готово')
        # self._dispatcher.register_message_handler(self._user_middleware(self._get_support_info), text='ℹ️ Консультация')
        # self._dispatcher.register_message_handler(self._user_middleware(self._get_support_info), text='✉️ Поддержка')
        self._dispatcher.register_message_handler(self._user_middleware(self._get_profile_info), text='👤 Мой аккаунт')
        self._dispatcher.register_message_handler(self._user_middleware(self._make_call), text='📞 Позвонить')
        self._dispatcher.register_message_handler(self._choose_pattern, state=GetAnswer.phone_number)
        # self._dispatcher.register_message_handler(self._user_middleware(self._get_qa_info), text='❓️ Вопрос-ответ')
        # self._dispatcher.register_message_handler(self._user_middleware(self._generate_phrase), aiogram.dispatcher.filters.Text(startswith="✨ Генерировать фразу "))
        # self._dispatcher.register_message_handler(self._user_middleware(self._admin_required(self._switch_to_admin_panel)), text='↕️ Админка')
        self._dispatcher.register_message_handler(self._user_middleware(self._admin_required(self._ask_paid_id)), text='Добавить подписку')
        self._dispatcher.register_message_handler(self._user_middleware(self._admin_required(self._ask_unpaid_id)), text='Убрать подписку')
        # self._dispatcher.register_message_handler(self._user_middleware(self._admin_required(self._access_users_list)), text='Список клиентов')
        self._dispatcher.register_message_handler(self._user_middleware(self._admin_required(self._users_amount)), commands=['users'])
        # self._dispatcher.register_message_handler(self._user_middleware(self._admin_required(self._increase_limits)), text='Увеличить лимиты')
        self._dispatcher.register_message_handler(self._set_paid_id, state=GetAnswer.answer_paid_id)
        # self._dispatcher.register_message_handler(self._user_middleware(self._paid_required(self._buy_db)), text='✅ Докупить БД')
        # self._dispatcher.register_message_handler(self._user_middleware(self._buy_program), text='✅ Купить программу')
        # self._dispatcher.register_message_handler(self._user_middleware(self._how_much), text='❓ Сколько стоит?')
        # self._dispatcher.register_message_handler(self._user_middleware(self._paid_required(self._download_program)), text='↙️ Скачать программу')
        self._dispatcher.register_message_handler(self._set_unpaid_id, state=GetAnswer.answer_unpaid_id)
        # self._dispatcher.register_message_handler(self._update_user_limit, state=GetAnswer.answer_limit)
        # self._dispatcher.register_message_handler(self._user_middleware(self._paid_required(self._send_win_tutorial)), text='Windows')
        # self._dispatcher.register_message_handler(self._user_middleware(self._paid_required(self._send_macos_tutorial)), text='MacOS')
        # self._dispatcher.register_message_handler(self._user_middleware(self._paid_required(self._send_android_tutorial)), text='Android')
        # self._dispatcher.register_message_handler(self._user_middleware(self._paid_required(self._send_ios_tutorial)), text='IOS')
        self._dispatcher.register_callback_query_handler(self._cancel_handler, aiogram.dispatcher.filters.Text(startswith="cancel"), state="*")
    
    async def _cancel_handler(self, call: aiogram.types.CallbackQuery, state: aiogram.dispatcher.FSMContext):
        current_state = await state.get_state()
        if current_state is not None:
            await state.finish()
        await self._show_menu(call.message, await self._user_storage.get_by_id(call.message.chat.id))

    def _user_middleware(self, func:typing.Callable) -> typing.Callable:
        async def wrapper(message:aiogram.types.Message, *args, **kwargs):
            user = await self._user_storage.get_by_id(message.chat.id)
            if user is None:
                # split_message = message.text.split()
                # if len(split_message) == 2 and split_message[1].isdigit() and await self._user_storage.get_by_id(int(split_message[1])):
                #     inviter_id = int(split_message[1])
                #     await self._user_storage.give_referal(inviter_id)
                #     inviter_user = self._user_storage.get_by_id(inviter_id)
                #     local_keyb = self._generate_menu_keyb(inviter_user)
                #     await self._bot.send_message(chat_id=inviter_id, text='❤️ Спасибо за приглашённого друга.\n\nКак и обещали - зачислили тебе 30 генераций!', reply_markup = local_keyb)
                user = User(
                    id = message.chat.id,
                    role = User.USER
                )
                # users = await self._user_storage.get_user_amount()
                # if int(users) % 100 == 0:
                #     await self._bot.send_message(chat_id=Config.admins_chat_id, text=f'Количество пользователей в боте достигло {int(users)}')
                await self._user_storage.create(user)
            elif user.role == User.BLOCKED:
                return wrapper
            await func(message, user)
        return wrapper
    
    async def _check_subscriptions(self):
        users = await self._user_storage.get_all_members()
        now = datetime.datetime.now()
        for user in users:
            if user.expire_date and user.expire_date < now and user.role in (User.PAID):
                # match user.role:
                #     case User.PAID:
                #         reply_markup = self._buy_inline_markup
                #     case User.PROF_LIMIT:
                #         reply_markup = self._continue_buy_inline_markup
                await self._user_storage.make_unpaid(user)
                await self._bot.send_message(user.id, "Ваша подписка закончилась")

    def _admin_required(self, func:typing.Callable) -> typing.Callable:
        async def wrapper(message:aiogram.types.Message, user:User, *args, **kwargs):
            if user.role == User.ADMIN:
                await func(message, user)
        return wrapper
    
    def _paid_required(self, func:typing.Callable) -> typing.Callable:
        async def wrapper(message:aiogram.types.Message, user:User, *args, **kwargs):
            if user.role in (User.PAID, User.ADMIN) or user.id in Config.gods:
                await func(message, user)
        return wrapper

    def _god_required(self, func:typing.Callable) -> typing.Callable:
        async def wrapper(message:aiogram.types.Message, user:User, *args, **kwargs):
            if user.id in Config.gods:
                await func(message, user)
        return wrapper
