from __future__ import unicode_literals
import json
import os
import time
# Get the absolute filepath to working directory
abs_filepath = os.path.abspath(os.path.dirname(__file__))
# Install the important packages
os.system('pip install -r' + os.path.join(abs_filepath, 'requirements.txt') )

import requests
from PIL import Image, ImageOps
from threading import Thread
from flask import Flask, request, send_file

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

# Function to show the users full-scale photos directly from cache
@app.route("/image=<img>", methods=['GET'])
def show_image(img):
    path = os.path.join(abs_filepath, '.image_cache', img + '.jpg')
    if os.path.isfile(path):
        return send_file(path, mimetype='image/jpg', cache_timeout=-1)
    else:
        return


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


# Separated thread_func to download shown image to cache
def download_photo_to_cache(user_id, photo_num):
    # Request the photo
    r = requests.get(sessionStorage[user_id]['photos'][photo_num], stream=True)
    # In case if we succeeded
    if r.status_code == 200:
        # Write response content into the ./.image_cache/ folder
        with open(os.path.join(abs_filepath, '.image_cache', user_id + '.jpg'), 'wb') as f:
            f.write(r.content)
        # Write this info into sessionStorage
        sessionStorage[user_id].update({'last_requested_photo': photo_num})
    return


# Function for uploading photos from cache to the album "VK_Gallery"
def upload_photo_to_server(user_id, path, token):
    album_id = ''
    # Request VK albums of the user
    albums = requests.get("https://api.vk.com/method/photos.getAlbums?access_token=" + token + "&v=5.126").json()['response']['items']
    # Go through them and get the one called "VK_Gallery"
    for item in albums:
        if item['title'] == 'VK_Gallery':
            album_id = str(item['id'])
    # If the user doesn't have "VK_Gallery" album, create it
    if album_id == '':
        album_id = str(requests.get("https://api.vk.com/method/photos.createAlbum?access_token=" + token \
            + "&title=VK_Gallery" + "&v=5.126").json()['response']['id'])
    # Now get the uploading url
    upload_url = requests.get('https://api.vk.com/method/photos.getUploadServer?access_token=' + token \
        + '&album_id=' + album_id + '&v=5.126').json()['response']['upload_url']
    # Upload using "curl_post_multipart.sh" script
    code = abs_filepath + '/curl_post_multipart.sh "" ' + path + ' "' + upload_url + '"'
    out = os.popen(code)
    # Parse the answer
    r = json.loads(out.read())
    # Save uploaded photo to album
    requests.get('https://api.vk.com/method/photos.save?access_token=' + token + '&album_id=' \
            + str(r['aid']) + '&server=' + str(r['server']) + '&photos_list=' + r['photos_list'] + '&hash=' + str(r['hash']) + '&v=5.126')
    return "Сохранила"


# Function for uploading photos to Yandex.Dialogs
def upload_photo_to_yandex_dialogs(user_id, res, photo_num, path=None):
    res['response']['text'] = "Вывожу на экран"
    url = 'https://dialogs.yandex.net/api/v1/skills/' + skill_id + '/images'
    return_url = ''
    # Check if we have to upload image by path or by address
    if path == None:
        headers = {'Authorization': 'OAuth ' + OAuth_id, 'Content-Type': 'application/json'}
        data = {'url': sessionStorage[user_id]['photos'][photo_num]}
        r = requests.post(url, headers=headers, json=data).json()
        return_url = sessionStorage[user_id]['photos'][photo_num]
        # Cache the image file
        Thread(target=download_photo_to_cache, args=[user_id, photo_num]).start()
    else:
        #photo_num = sessionStorage[user_id]['last_requested_photo']
        code = abs_filepath + '/curl_post_multipart.sh ' + OAuth_id + ' ' + path + ' "' + url + '"'
        out = os.popen(code)
        r = json.loads(out.read())
        return_url = 'https://aliceresponse.azurewebsites.net/image=' + str(user_id)
    # Form the response
    res['response']['card'] = {
        'type': 'BigImage',
        'image_id': r['image']['id'],
        'title': "Изображение " + str(photo_num),
        'button': {
            'text': "Открыть изображение " + str(photo_num),
            'url': return_url
        }
    }
    # Schedule the used image removal from Yandex.Dialogs small storage
    Thread(target=photo_autoremove, args=[r['image']['id']]).start()
    return res


# Dialog handling function (here all the linguistic checks are made)
def handle_dialog(req, res):
    user_id = req['session']['user']['user_id']

    if req['session']['new']:
        # Это новый пользователь.
        # Инициализируем сессию и поприветствуем его.
        '''
        sessionStorage[user_id].update({
            'suggests': [
                "Не хочу.",
                "Не буду.",
                "Отстань!",
            ]
        })
        '''
        if 'first_name' in sessionStorage[user_id] and 'last_name' in sessionStorage[user_id]:
            res['response']['text'] = 'Приветствую, ' + sessionStorage[user_id]['first_name'] \
                + ' ' + sessionStorage[user_id]['last_name'] + ', рада вас видеть!'
        else:
            res['response']['text'] = 'Извините, что-то пошло не так с авторизацией'
        #res['response']['buttons'] = get_suggests(user_id)
        return

    '''
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
    '''

    # Get the original utterance into a variable
    original_utterance = req['request']['original_utterance'].lower()
    # Image cache path
    path = os.path.join(abs_filepath, '.image_cache', user_id + '.jpg')

    # Check if the user has requested some photo
    if 'покажи фото' in original_utterance:
        # Trying to get photo number, zero if none is given
        photo_num = int(next((i['value'] for i in req['request']['nlu']['entities'] if i['type'] == 'YANDEX.NUMBER'), 0 ))
        # Max length of the photos array
        max_len = len(sessionStorage[user_id]['photos']) - 1
        # Boundaries check
        if photo_num > max_len:
            photo_num = max_len
        elif photo_num < 0:
            photo_num = 0
        # Upload the result
        res = upload_photo_to_yandex_dialogs(user_id, res, photo_num)
    # Swipe photo forward
    elif 'следующее' in original_utterance:
        if 'last_requested_photo' in sessionStorage[user_id]:
            photo_num = int(sessionStorage[user_id]['last_requested_photo']) + 1
            if photo_num > len(sessionStorage[user_id]['photos']) - 1:
                photo_num = 0
            res = upload_photo_to_yandex_dialogs(user_id, res, photo_num)
        else:
            res['response']['text'] = 'Пожалуйста, сначала выберите изображение'
    # Swipe photo backward
    elif 'предыдущее' in original_utterance:
        if 'last_requested_photo' in sessionStorage[user_id]:
            photo_num = int(sessionStorage[user_id]['last_requested_photo']) - 1
            if photo_num < 0:
                photo_num = len(sessionStorage[user_id]['photos']) - 1
            res = upload_photo_to_yandex_dialogs(user_id, res, photo_num)
        else:
            res['response']['text'] = 'Пожалуйста, сначала выберите изображение'
    # Apply some filter chosen by the user
    elif 'фильтр' in original_utterance:
        if os.path.isfile(path) and 'last_requested_photo' in sessionStorage[user_id]:
            # Apply filter if it's requested
            img = Image.open(path)
            if 'чёрно-белый' in original_utterance:
                img = ImageOps.grayscale(img)
            elif 'пастеризация' in original_utterance:
                img = ImageOps.posterize(img, 3)
            elif 'отражение' in original_utterance or 'отражающий' in original_utterance:
                img = ImageOps.mirror(img)
            img.save(path)
            # Show it to user
            upload_photo_to_yandex_dialogs(user_id, res, sessionStorage[user_id]['last_requested_photo'], path)
        else:
            res['response']['text'] = 'Пожалуйста, сначала выберите изображение'
    # Developer's only case to show cached image
    elif 'покажи кэш' in original_utterance:
        if os.path.isfile(path) and 'last_requested_photo' in sessionStorage[user_id]:
            # Upload photo to Yandex.Dialogs small storage
            res = upload_photo_to_yandex_dialogs(user_id, res, sessionStorage[user_id]['last_requested_photo'], path)
        else:
            res['response']['text'] = 'В кэше нет изображения'
    # Cancel all changes made
    elif 'отмени' in original_utterance:
        if os.path.isfile(path) and 'last_requested_photo' in sessionStorage[user_id]:
            # Get previously requestet photo's number
            photo_num = sessionStorage[user_id]['last_requested_photo']
            # Re-download it to cache to clear the changes
            Thread(target=download_photo_to_cache, args=[user_id, photo_num]).start()
            res['response']['text'] = 'Поняла'
        else:
            res['response']['text'] = 'Пока что мне нечего отменить'
    # Save photo to VK album
    elif 'сохрани' in original_utterance:
        if os.path.isfile(path) and 'last_requested_photo' in sessionStorage[user_id]:
            # Upload photo to VK_Gallery album of the user
            res['response']['text'] = upload_photo_to_server(user_id, path, req['session']['user']['access_token'])
        else:
            res['response']['text'] = "Пока что мне нечего сохранить"
    # In other cases the standard behaviour
    else:
        res['response']['text'] = 'К сожалению, я не знаю команды "%s"' % (req['request']['original_utterance'])
    # Pick up suggestions
    #res['response']['buttons'] = get_suggests(user_id)

'''
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
'''