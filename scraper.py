#!/usr/bin/env python
# -*- coding: utf-8 -*-


import requests
requests.packages.urllib3.disable_warnings() 
import lxml.html
import time
import re
import json
import logging
from collections import namedtuple


s = requests.Session()
headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:67.0) DeJure",
            "Connection": "keep-alive",
            "Referer": None,
            "Host": "hcj.gov.ua"
        }

# сервер, шлях
SRV = "https://hcj.gov.ua"
PATH = "/announces"
# constants
TYPE_TALK_RE = re.compile(
    "^Засідання (?:(?P<name>Першої|Другої|Третьої) Дисциплінарної палати )?Вищої ради правосуддя$")
DIGIT_SECTION_RE = re.compile("^\d")
OTHER = re.compile("^\d+?\.?\s+?Різне$")
DP_DICT = {
    "першої": "dp1",
    "другої": "dp2",
    "третьої": "dp3"
}


def get_cvk_page(url):
    '''Повертає текст сторінки або нічого
    '''
    res = s.get(url, headers=headers, verify = False)
    # print(res.encoding)
    # print(res.url)
    res.encoding="utf-8"
    if res.status_code != 200:
        print(f"Error <= {url}")
        return
    return res.text


def get_proj_link(url):
    project_res = get_cvk_page(SRV + url)
    proj_content = lxml.html.fromstring(project_res)
    proj_link = proj_content.xpath(
        '//*[starts-with(@id, "node-")]/div[2]/div/div/p[2]/a/@href')
    return proj_link


def extract_lost_question(text, last_title):
    out = None
    last_title = last_title.replace(".", "\\.") + ".+\\n"
    full_text = "\n".join([y for x in text if (y:=x.strip())])
    if (m:=re.search(
            rf"^{last_title}(.+?(?:.+)\n(?:.+?\n)+)Секретар ",
            full_text, re.MULTILINE)) is None:
        # Not found
        return ''
    question = m.groups(1)
    question = re.sub("\s{1,}", ' ', question[0])
    question_data = extract_spokesperson(question) + [False]
    try:
        out = question_data
    except:
        out = [question[0], None, True]
    finally:
        return out


def extract_project(element):
    # елемнтом виступає article
    titles = element.xpath('.//p[@class="rtejustify"]')
    if len(titles) == 1:
        try:
            if titles[0].xpath('.//text()')[0] == '\xa0':
                titles = []
        except ValueError:
            pass
    if not titles:
        titles = element.xpath('.//p//u')
    titles_list = []
    for p in titles:
        # print("> ", "'" + p.xpath('.//text()') + "'")
        # print(p.xpath('.//text()'))
        title = "".join(p.xpath('.//text()')).strip()
        if not title or DIGIT_SECTION_RE.search(title) is None:
            continue
        #  re.sub(pattern, repl, string, count=0, flags=0)
        title = re.sub("[:.,]$", "", title)
        # print(title)
        titles_list.append(title)
    # питання
    question_lists = element.xpath(".//ol")
    questions = extract_questions(question_lists)
    # print("questions", questions)
    if len(titles_list) - len(questions) == 1:
        # пошук останнього питання, яке знаходиться поза списком
        last_title = titles_list[-1]
        lost_question = extract_lost_question(
            element.xpath("//article//p//text()"), last_title)
        if not lost_question:
            questions.append([])
        else:
            questions.append([lost_question])
    q_dict = [dict(zip(["title", "questions"], q)) for q in
              [x for x in zip(titles_list, questions)]]
    for question in q_dict:
        question["questions"] = [
            dict(zip(["question", "speaker", "error"], q))
            for q in question["questions"]]
    return q_dict


def extract_questions(question_lists):
    # print("question_lists", question_lists,)
    questions_sections = [
        [spokesperson_fix(" ".join(q.xpath(".//text()"))) for q in qlist]
        for qlist in question_lists]
    new_sections = []
    for section in questions_sections:
        new_section = []
        for q in section:
            new_section.append(extract_spokesperson(q) + [False])
        new_sections.append(new_section)
    return new_sections


def spokesperson_fix(string):
    string = re.sub("\s+", " ", re.sub('\xa0', ' ', string))
    string = re.sub('\((?:\s+?)?(.+?)(?:\s+?)?\)', '(\\1)', string)
    string = re.sub(" \.", ".", string)
    if not re.search("Д\s+?оповідач", string, re.I):
        return string
    return re.sub("Д\s+?оповідач", 'Доповідач', string)


def extract_spokesperson(string):
    splitted = [re.sub(";$", "", x.strip()) for x in
                re.split("\(Доповідач(?:\s+?[-–—])?(.+?)\)", string, re.I)]
    splitted = [x.strip() for x in splitted if x]
    # print("splitted", splitted)
    if len(splitted) == 1:
        splitted.append(None)
    return splitted


def get_disciplinary_project(url, proj_type=None):
    proj_res = get_cvk_page(url)
    proj_content = lxml.html.fromstring(proj_res)
    docx_link = proj_content.xpath(
        '//article[starts-with(@id, "node-")]/div[2]//a/@href')
    docx_name = proj_content.xpath(
        '//article[starts-with(@id, "node-")]/div[2]//a/text()')
    article = proj_content.xpath('//*[starts-with(@id, "node-")]')
    project = extract_project(article[0])
    return {"file_name": docx_name[0],
            "file_link": docx_link[0],
            "session_project": project}


def process_vrp_questions(questions):
    for q in questions:
        if q['questions'] == []:
            continue
        new_content = [x + ")" if re.match("^\d+$", x) else x
                       for x in q['questions']]
        q['questions'] = " ".join(new_content).replace(
            "- у зв’язку з поданням заяви про відставку", "")
        q['questions'] = [
            re.sub("[\:\.\,\;\s]$", "", y).strip() for x in
            re.split("\d+?\) ", q['questions']) if (y:=x.strip())]
    # Коротенькі питання, що менші ніж 7 символів, зливаються з першим питанням
    # у списку питань. Питання потім видаляється, тому перелік питань може
    # бути порожнім
    for que in questions:
        q_title, q_body = que["title"], que["questions"]
        if len(q_title) > 7 or not q_body:
            continue
        first_question = q_body[0]
        que["title"] = q_title + " " + first_question
        que["questions"].remove(first_question)
    return questions


def extract_vrp_project(element):
    # елемнтом виступає article
    titles = element.xpath('.//p//u/text()')
    clean_titles = [re.sub("\s+", " ", x).strip() for x in titles]
    clean_titles = [
        re.sub(r'[\s:.]$', '', x).strip() for x in clean_titles
        if DIGIT_SECTION_RE.search(x)]
    # text = element.xpath(".//p//text()")
    text = element.xpath(".//*[self::li or self::p]//text()")
    text = [re.sub("\s+", " ", x).strip() for x in text]
    text = [y for x in text if (y:=re.sub('[\s:.]$', '', x).strip())]
    questions = []
    q = None
    first_line = False
    for line in text:
        if line in clean_titles:
            first_line = True
            if q is not None:
                questions.append(q)
            q = {"title": line, "questions": []}
            if line == text[-1]:
                questions.append(q)
            continue
        else:
            if not first_line:
                continue
            q["questions"].append(line)
    return process_vrp_questions(questions)


def get_vrp_project(url, proj_type=None):
    # print("VRP_Url", url)
    # proj_link[0], proj_type=type_talk
    proj_res = get_cvk_page(url)
    proj_content = lxml.html.fromstring(proj_res)
    docx_link = proj_content.xpath(
        '//article[starts-with(@id, "node-")]/div[2]//a/@href')
    docx_name = proj_content.xpath(
        '//article[starts-with(@id, "node-")]/div[2]//a/text()')
    # print(docx_link, docx_name)
    article = proj_content.xpath('//*[starts-with(@id, "node-")]')
    project = extract_vrp_project(article[0])
    return {"session_project": project,
            "file_name": docx_name[0],
            "file_link": docx_link[0]}


def get_project_data(list_item):
    # дата засідання
    talk_date = list_item.xpath(
        "./div[1]/div[@class='field-content']/span[@class='date-display-single']/text()")
    # назва засідання
    talk_name = list_item.xpath(
        "./div[2]/span[@class='field-content']/a/text()")
    # тип засідання
    try:
        print(f"> {talk_name[0]}")
    except:
        print(talk_name)
    if (m:=TYPE_TALK_RE.match(talk_name[0])) is None:
        # не ВРП, не палата
        return
    name_org = m.group('name')
    if name_org is None:
        # сама ВРП
        type_talk = "vrp"
    else:
        # print(name_org)
        # палати
        type_talk = DP_DICT[name_org.lower()]
    # посилання на проєкт зі сторінки анонсу
    talk_href = list_item.xpath(
        "./div[2]/span[@class='field-content']/a/@href")
    # номер засідання
    session_num = talk_href[0].split('-')[-1]
    talk_code = type_talk + "_" + session_num.zfill(4)
    # print(talk_code)
    # посилання на власне проєкт
    proj_link = get_proj_link(talk_href[0])
    # print(proj_link)
    if type_talk == "vrp":
        project_data = get_vrp_project(proj_link[0], proj_type=type_talk)
        data = {
            "project": project_data["session_project"],
            "meta": {"talk_date": talk_date[0],
                     "talk_name": talk_name[0],
                     "type_talk": type_talk,
                     "talk_href": talk_href[0],
                     "talk_code": talk_code,
                     "proj_link": proj_link[0],
                     "file_name": project_data["file_name"],
                     "file_link": project_data["file_link"]
                     }
                }
    elif type_talk in ["dp1", "dp2", "dp3"]:
        project_data = get_disciplinary_project(
                       proj_link[0], proj_type=type_talk)
        data = {
            "project": project_data["session_project"],
            "meta": {"talk_date": talk_date[0],
                     "talk_name": talk_name[0],
                     "type_talk": type_talk,
                     "talk_href": talk_href[0],
                     "talk_code": talk_code,
                     "proj_link": proj_link[0],
                     "file_name": project_data["file_name"],
                     "file_link": project_data["file_link"]
                     }
                }
    return data


ann_res = get_cvk_page(SRV + PATH)
ann_content = lxml.html.fromstring(ann_res)
list_items = ann_content.xpath('//*[@id="block-system-main"]/div/div/div/div')
hcj_data_out = {}
for list_item in list_items:
    data = get_project_data(list_item)
    if data is None:
        continue
    if data["meta"]["type_talk"] not in hcj_data_out:
        hcj_data_out[data["meta"]["type_talk"]] = {}
    hcj_data_out[data["meta"]["type_talk"]][data["meta"]["talk_code"]] = data
    with open(f'hcj_{data["meta"]["talk_code"]}.json', "w") as f:
        json.dump(data, f, ensure_ascii=False)
    time.sleep(0.85)


with open(f'hcj_data.json', "w") as f:
        json.dump(hcj_data_out, f, ensure_ascii=False)
