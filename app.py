from __future__ import unicode_literals
import json
import os
import time
# Get the absolute filepath to working directory
abs_filepath = os.path.abspath(os.path.dirname(__file__))
# Install the important packages
os.system('pip install -r' + os.path.join(abs_filepath, 'requirements.txt') )

import requests
from PIL import Image
from threading import Thread
from flask import Flask, request

# Run the main app
app = Flask(__name__)

# Default session storage for user data
sessionStorage = {}
# Read your ID's from file
credentials_filepath = os.path.join(abs_filepath, "credentials.txt")
with open(credentials_filepath) as f:
    # Skill ID
    skill_id = f.readline().rstrip(os.linesep)
    # OAuth ID
    OAuth_id = f.readline().rstrip(os.linesep)


# Flask app's root pathway setup
@app.route("/", methods=['POST'])
def main():
    # If the user is unregistered, then authenticate
    if 'access_token' not in request.json['session']['user']:
        return authenticate()
    # Get unique user id (one for all surfaces)
    user_id = request.json['session']['user']['user_id']
    # Sync the user data if don't have it
    if user_id not in sessionStorage:
        sessionStorage.update({user_id: {}})
        sync_user(token=request.json['session']['user']['access_token'], user_id=user_id)
    # In case if account linking just complete, start dialogue again
    if 'account_linking_complete_event' in request.json:
        request.json['session']['new'] = True
    # Form the response template
    response = {
        "version": request.json['version'],
        "session": request.json['session'],
        "response": {
            "end_session": False
        }
    }
    # Process requested command
    handle_dialog(request.json, response)
    # Return response
    return json.dumps(
        response,
        ensure_ascii=False,
        indent=2
    )


# Tell Alisa that we need to authenticate at VK.api
def authenticate():
    # Form the response
    response = {
        "version": request.json['version'],
        "session": request.json['session'],
        "start_account_linking": {}
    }
    # Jsonify response
    return json.dumps(
        response,
        ensure_ascii=False,
        indent=2
    )


# Sync user info and photos with our VK account
def sync_user(token, user_id):
    # Create the new default entities
    user = {}
    photos = []
    # Obtain resources from VK.api
    user = requests.get("https://api.vk.com/method/users.get?access_token=" + token + "&v=5.126").json()['response'][0]
    photos = requests.get("https://api.vk.com/method/photos.getAll?access_token=" + token + "&offset=0&count=200&v=5.126").json()['response']['items']
    # Collapse photos into user
    user.update({'photos': []})
    for p in photos:
        try:
            user['photos'].append(p['sizes'][-1]['url'])
        except:
            pass
    # Update session storage
    sessionStorage.update({str(user_id): user})


# Separated thread_func to automatically remove used photos
def photo_autoremove(photo_id):
    # Set the time limit after which we will remove photo_id from Yandex.dialogs storage
    time.sleep(5)
    # Construct the url
    url = 'https://dialogs.yandex.net/api/v1/skills/' + skill_id + '/images/' + photo_id
    # Set headers
    headers = {'Authorization': 'OAuth ' + OAuth_id}
    # Send DELETE request
    requests.delete(url, headers=headers)
    return

def download_photo_to_cache(user_id, photo_num):
    # Request the photo
    r = requests.get(sessionStorage[user_id]['photos'][photo_num], stream=True)
    # In case if we succeeded
    if r.status_code == 200:
        # Write response content into the .image_cache folder
        with open(os.path.join(abs_filepath, '.image_cache', user_id + '.jpg'), 'wb') as f:
            f.write(r.content)
        # Write this info into sessionStorage
        sessionStorage[user_id].update({'last_requested_photo': photo_num})
    return

# Функция для непосредственной обработки диалога.
def handle_dialog(req, res):
    user_id = req['session']['user']['user_id']

    if req['session']['new']:
        # Это новый пользователь.
        # Инициализируем сессию и поприветствуем его.

        sessionStorage[user_id].update({
            'suggests': [
                "Не хочу.",
                "Не буду.",
                "Отстань!",
            ]
        })
        try:
            res['response']['text'] = 'Приветствую, ' + sessionStorage[user_id]['first_name'] \
                + ' ' + sessionStorage[user_id]['last_name'] + ', рада вас видеть!'
        except:
            res['response']['text'] = 'Привет! Купи слона!'
        res['response']['buttons'] = get_suggests(user_id)
        return

    # Обрабатываем ответ пользователя.
    if req['request']['original_utterance'].lower() in [
        'ладно',
        'куплю',
        'покупаю',
        'хорошо',
    ]:
        # Пользователь согласился, прощаемся.
        res['response']['text'] = 'Слона можно найти на Яндекс.Маркете!'
        return

    # Check if the user has requested some photo
    if 'покажи фото' in req['request']['original_utterance'].lower():
        # Make Alisa tell the following phrase
        res['response']['text'] = "Вывожу на экран"
        # Extract the photo number from phrase if any
        try:
            photo_num = int(req['request']['nlu']['tokens'][-1])
            max_len = len(sessionStorage[user_id]['photos'])
            if photo_num > max_len:
                photo_num = max_len
        except:
            photo_num = 0
        # Post requested image into Yandex.dialogs small storage
        url = 'https://dialogs.yandex.net/api/v1/skills/' + skill_id + '/images'
        headers = {'Authorization': 'OAuth ' + OAuth_id, 'Content-Type': 'application/json'}
        data = {'url': sessionStorage[user_id]['photos'][photo_num]}
        r = requests.post(url, headers=headers, json=data)
        # Display the image card
        res['response']['card'] = {
            'type': 'BigImage',
            'image_id': r.json()['image']['id'],
            'title': "Изображение " + str(photo_num),
            'button': {
                'text': "Открыть изображение " + str(photo_num),
                'url': sessionStorage[user_id]['photos'][photo_num]
            }
        }
        # Cache the image file
        Thread(target=download_photo_to_cache, args=[user_id, photo_num]).start()
        # Schedule the used image removal from yandex.dialogs small storage
        Thread(target=photo_autoremove, args=[r.json()['image']['id']]).start()
    # Make Alisa to show us the image that stored within user cache
    elif 'покажи кэш' in req['request']['original_utterance'].lower():
        path = os.path.join(abs_filepath, '.image_cache', user_id + '.jpg')
        if os.path.isfile(path) and 'last_requested_photo' in sessionStorage[user_id]:
            photo_num = sessionStorage[user_id]['last_requested_photo']
            res['response']['text'] = "Вывожу на экран"
            url = 'https://dialogs.yandex.net/api/v1/skills/' + skill_id + '/images'
            code = abs_filepath + '/curl_post_multipart.sh ' + OAuth_id + ' ' + path + ' "' + url + '"'
            out = os.popen(code)
            r = json.loads(out.read())
            res['response']['card'] = {
                'type': 'BigImage',
                'image_id': r['image']['id'],
                'title': "Изображение " + str(photo_num),
                'button': {
                    'text': "Открыть изображение " + str(photo_num),
                    'url': sessionStorage[user_id]['photos'][photo_num]
                }
            }
            Thread(target=photo_autoremove, args=[r['image']['id']]).start()
        else:
            res['response']['text'] = 'В кэше нет изображения'
    else:
        # In other cases the standard behaviour
        res['response']['text'] = 'Все говорят "%s", а ты купи слона!' % (req['request']['original_utterance'])
    # Pick up suggestions
    res['response']['buttons'] = get_suggests(user_id)


# Функция возвращает две подсказки для ответа.
def get_suggests(user_id):
    session = sessionStorage[user_id]

    # Выбираем две первые подсказки из массива.
    suggests = [
        {'title': suggest, 'hide': True}
        for suggest in session['suggests'][:2]
    ]

    # Убираем первую подсказку, чтобы подсказки менялись каждый раз.
    session['suggests'] = session['suggests'][1:]
    sessionStorage[user_id] = session

    # Если осталась только одна подсказка, предлагаем подсказку
    # со ссылкой на Яндекс.Маркет.
    if len(suggests) < 2:
        suggests.append({
            "title": "Ладно",
            "url": "https://market.yandex.ru/search?text=слон",
            "hide": True
        })

    return suggests