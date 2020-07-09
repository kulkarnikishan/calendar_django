import csv
import os
import threading

import xlrd
from django.core.mail import EmailMessage
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse, FileResponse, Http404
# from django.views.generic import View
import requests
# from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta

from django.template.loader import render_to_string
from pdfkit import pdfkit

from revio_proj.settings import revio_api_key, superSaas_api_key, superSaaS_acc_name, BASE_DIR
from rest_framework.decorators import api_view
import json
from fpdf import FPDF, HTMLMixin
import pandas as pd

# Create your views here.


def index(request):
    return HttpResponse("<h1>Welcome to Calendar project</h1>")


def get_labeled_value(fields, label):
    match_val = next((item for item in fields if item['label'] == label), None)
    if match_val:
        return match_val['value']
    else:
        return None


def get_related_orders(request):
    """
    Get related orders based on the customer_id
    :param request: https://restapi.rev.io/v1/Orders?customer_id=<customer_id>
    :return: related orders
    """
    ret = []
    res = {}
    # this is to get customer id if we receive an order id from the front end
    # order_id = request.GET.get('order_id', None)
    order_id = 5111
    headers = {
        'accept': "application/json",
        'authorization': revio_api_key
    }
    if order_id == None:
        return JsonResponse({'success': False, 'data': 'missing order_id'})
    order_info_url = "https://restapi.rev.io/v1/Orders?order_id={}".format(order_id)
    try:
        order_info_response = requests.request("GET", order_info_url, headers=headers)
    except Exception as e:
        return JsonResponse({'success': False, 'data': str(e)})
    order_info_resp_json = json.loads(order_info_response.text)
    order_info_response_json = order_info_resp_json['records'][0]
    customer_id = order_info_response_json.get('customer_id')
    # customer_id = request.args.get('customer_id')
    # customer_id = 63684

    orders_url = "https://restapi.rev.io/v1/Orders?customer_id={}".format(customer_id)
    response = requests.request("GET", orders_url, headers=headers)
    response_json = response.json()
    for order in response_json['records']:
        res['order_number'] = order.get('order_id')
        # res['order_type'] = order.get('order_type')
        res['customer_id'] = order.get('customer_id')
        res['provider_id'] = order.get('provider_id')
        res['request_id'] = order.get('request_id')
        res['pon'] = order.get('pon')
        fields = order['fields']
        res['ttu_date'] = get_labeled_value(fields, 'Activation Date/TTU')
        res['ttu_time'] = get_labeled_value(fields, 'Activation Time /TTU')
        res['ttu_time_zone'] = get_labeled_value(fields, 'Apt. Time Zone')
        res['port_date'] = get_labeled_value(fields, 'Port Date')
        res['port_time'] = get_labeled_value(fields, 'Port Time')
        res['port_time_zone'] = get_labeled_value(fields, 'Port Time Zone')
        res['Appointment_Id'] = get_labeled_value(fields, 'Appointment ID')
        res['Schedule_Id'] = get_labeled_value(fields, 'Activator ID')

        if res['ttu_date'] and res['ttu_time'] and res['port_date'] and res['port_time']:
            res['order_type'] = 'New'
        elif res['ttu_date'] and res['ttu_time']:
            res['order_type'] = 'TTU'
        elif res['port_date'] and res['port_time']:
            res['order_type'] = 'Port'

        if str(order['status']) != 'NEW' and str(order['status']) != 'CONFIRMED':
            continue
        order_provider_id = order['provider_id']
        request_id = order['request_id']
        request_service_json = getObjects('RequestServices', {'request_id': request_id})
        for request_service in request_service_json['records']:
            request_service_id = request_service['request_service_id']
            service = getObjects('Services', {'request_service_id': request_service_id})['records'][0]
            provider_id = service['provider_id']
            service_customer_id = service['customer_id']
            if str(provider_id) != str(order_provider_id) or str(service_customer_id) != str(customer_id):
                continue
            service_type_id = service['service_type_id']
            service_type_json = getObjects('ServiceTypes', {'service_type_id': service_type_id})['records'][0]
            service_type = getValue(service_type_json, fieldType='built-in', field='description')
            # res['service_type'] = service_type
            res.update({'service_type': service_type})
        ret.append(res.copy())

    # This API is to get customer info
    cust_url = 'https://restapi.rev.io/v1/Customers/Metadata?customer_id={}'.format(customer_id)
    cust_response = requests.request("GET", cust_url, headers=headers)
    cust_res = cust_response.json()
    ret.append({'customer_info': cust_res})
    return JsonResponse({'success': True, 'data': ret})


def get_activation_names(request):
    """
    :param request: https://supersaas.com/api/schedules.json?account=<account_name>&api_key=<api_key>
    :return: list of activation names
    """
    url = "https://supersaas.com/api/schedules.json?account={}&api_key={}".format(
        superSaaS_acc_name, superSaas_api_key)
    response = requests.request("GET", url)
    # response = requests.get(url, auth=HTTPBasicAuth('CallOne', 'bTL8QZmn67kSHMo_1DZlqg'))
    res = response.json()
    # 481678-Activations, 492683-Services Activations need to be removed from the res
    filtered_res = [i for i in res if i['id'] not in [481678, 492683]]
    return JsonResponse({'success': True, 'data': filtered_res})


def get_available_slots(request):
    """
    481678 is activation schedule id used to get activation names. There are other two types of schedules in
    the SuperSaaS for CallOne namely IT and Service Activations. Make this id dynamic if you get
    requirements in future
    date format should be YYYY-MM-DD HH:MM:SS
    :param request: https://supersaas.com/api/free/481678.json?from=<datetime>&account=<>&api_key=your_api_key
    :return: list of schedules
    """
    # get today's date month and year
    now = datetime.now()
    from_date = now.strftime("%Y-%m-%d %H:%M:%S")

    # get 1st of the current month
    # today = datetime.today()
    # from_date = datetime(today.year, today.month, 1)

    # resource_id = request.args.get('resource_id')
    resource_id = 492685
    if resource_id:
        # get list of avilable slot for selected activation name or resource
        url = "https://www.supersaas.com/api/free/{}.json?from={}&api_key={}&maxresults=31".format(
            resource_id, from_date, superSaas_api_key)
    else:
        url = 'https://supersaas.com/api/free/481678.json?from={}&account={}&api_key={}'.format(from_date,
                                                                                                superSaas_api_key, superSaaS_acc_name)

    response = requests.request("GET", url)
    res = response.json()

    return JsonResponse({'success': True, 'data': res})


def getValue(object_json, fieldType, field):
    "This function will get a value from Rev.io given the object information in json format"

    if fieldType == 'built-in':
        return object_json[field]
    elif fieldType == 'additional':
        value = None
        for additionalField in object_json['fields']:
            if additionalField['label'] == field:
                value = additionalField['value']
                break
        return value
    elif fieldType == 'address':
        return object_json['service_address'][field]


def getObjects(objectType, queryDict, pageSize=None, page=None):
    url = "https://restapi.rev.io/v1/" + str(objectType)

    query = dict()
    for queryField, queryFieldValue in queryDict.items():
        queryKey = "search." + str(queryField)
        query[queryKey] = str(queryFieldValue)

    if pageSize is not None:
        query["search.page_size"] = str(pageSize)
    if page is not None:
        query["search.page"] = str(page)

    headers = {
        'accept': "application/json",
        'authorization': "Basic YXBpdXNlckBjYWxsb25lLmNvbUBjYWxsb25lOm8zcmg1TCZKaE9FQ081eEo="
    }

    response = requests.request("GET", url, headers=headers, params=query)
    response_json = json.loads(response.text)
    return response_json


@api_view(['POST'])
def post_bookings(request):
    """
    :param request:
    :return:
    """
    meeting = sync_meetings()
    if type(meeting) == list:
        meeting_id = meeting[0]
        dialin_number = meeting[1]
        meeting_url = meeting[2]
    else:
        res = "meeting id is not avaible"
        return JsonResponse({'success': False, 'data': res})
    res = ""
    d = request.data
    resdate = d['start'].split()
    # full_name = "{}/{}/{}/{}/{}".format(d['Order_Type'],d['Service_Type'],d['PON'], d['Customer_Account_Number'],d['Customer_Name'])

    full_name = d['schedule_name']
    PM_name = ''
    PM_email_id = ''
    order_id = request.data['orders'][0].get('order_id')
    orders = getObjects('Orders', {'order_id': order_id})
    customer_id = orders['records'][0]['customer_id']
    for row in orders['records'][0]['fields']:
        if row['field_id'] == 108:
            name = row['value'].split(' ')
            PM_name = row['value']
            PM_email_id = name[0][0] + name[1] + '@CallOne.com'
    techspec = 'http://etools.callone.com/ndd/techspec/%s' % customer_id
    description = ''
    ord_len = len(request.data['orders'])
    for i in range(ord_len):
        ser_no = i + 1
        o_id = request.data['orders'][i].get('order_id')
        order_info = getObjects('Orders', {'order_id': o_id})
        customer_id = order_info['records'][0]['customer_id']
        pon = order_info['records'][0]['pon']
        order_type = order_info['records'][0]['order_type']
        if ser_no == 1:
            description += '{}){}/{}/{}'.format(ser_no, o_id, pon, order_type)
        else:
            description += ' {}){}/{}/{}'.format(ser_no, o_id, pon, order_type)
    url = 'https://www.supersaas.com/api/bookings.json?schedule_id={}&api_key=bTL8QZmn67kSHMo_1DZlqg&booking[start]={}&booking[finish]={}&booking[full_name]={}&booking[description]={}' \
          '&booking[field_1_r]={}&booking[field_2_r]={}'.format(
        d['schedule_id'], d['start'], d['finish'], full_name, description, 'In progress', techspec)
    response = requests.request("POST", url)
    if response.status_code == 201:

        url = 'https://www.supersaas.com/api/bookings.json?schedule_id={}&api_key=bTL8QZmn67kSHMo_1DZlqg&start={}&limit=1'.format(
            d['schedule_id'], d['start'])
        appointment = requests.request("GET", url)
        acc = appointment.text
        convacc = json.loads(acc)
        appointment_id = convacc[0]['id']
        ret = []
        headers = {
            'accept': "application/json",
            'authorization': revio_api_key
        }
        for i in d['orders']:
            url = "https://restapi.rev.io/v1/Orders?order_id={}".format(i['order_id'])
            getresponse = requests.request("GET", url, headers=headers)
            orderres = getresponse.json()
            ret.append(res)
            for j in orderres['records'][0]['fields']:
                if j['field_id'] == 143:
                    j['value'] = appointment_id
                if j['field_id'] == 148:
                    j['value'] = d['schedule_id']
                if i['datetype'] == 'ttu':
                    if j['field_id'] == 131:
                        j['value'] = resdate[0]
                    if j['field_id'] == 126:
                        j['value'] = resdate[1]
                    if j['field_id'] == 122:
                        j['value'] = ''
                    if j['field_id'] == 123:
                        j['value'] = ''
                if i['datetype'] == 'port':
                    if j['field_id'] == 122:
                        j['value'] = resdate[0]
                    if j['field_id'] == 123:
                        j['value'] = resdate[1]
                    if j['field_id'] == 131:
                        j['value'] = ''
                    if j['field_id'] == 126:
                        j['value'] = ''
            puturl = "https://restapi.rev.io/v1/Orders/{}".format(i['order_id'])
            putdata = json.dumps(orderres['records'][0])
            headers = {
                'accept': "application/json",
                'authorization': revio_api_key,
                'content-type': "text/json"
            }
            updateresponse = requests.put(puturl, data=putdata, headers=headers)

            if i['datetype'] == 'ttu':
                task_url = 'https://restapi.rev.io/v1/Tasks?order_id={}&subject=Scheduling Pre-Install and Activation'.format(
                    i['order_id'])
                task_st_update = update_task_status(task_url)
            if i['datetype'] == 'port':
                task_url = 'https://restapi.rev.io/v1/Tasks?order_id={}&subject=Schedule Activation with Service Activation'.format(
                    i['order_id'])
                task_st_update = update_task_status(task_url)
            subjects = ['Schedule Preinstall TTU and PORT Activation with Customer & Service Activations', 'Schedule Test and Accept']
            for sub in subjects:
                task_url = 'https://restapi.rev.io/v1/Tasks?order_id={}&subject={}'.format(i['order_id'], sub)
                task_st_update = update_task_status(task_url)

            if orderres['records'][0]['customer_id']:
                customer_id = orderres['records'][0]['customer_id']
                noteurl = "https://restapi.rev.io/v1/Notes"

                headers = {
                    'accept': "application/json; charset=utf-8",
                    'authorization': revio_api_key,
                    'content-type': "text/json"
                }

                note_data = {
                    'subject': 'Appointment created in SuperSaaS for appointment id {}'.format(
                        appointment_id),
                    'body': 'Appointment has scheduled by {} with {} on {}.The meeting id is {} and dialin number is {}'.format(
                        PM_name,
                        d['schedule_name'],
                        str(resdate[0]),
                        meeting_id,
                        dialin_number),
                    'customer_id': customer_id,
                    'order_id': i['order_id'],
                    'note_type_id': 1012,
                }
                response = requests.post(noteurl, data=json.dumps(note_data), headers=headers)
        res = 'successfully added appointment'
        threading.Thread(target=techSpec, args=(request, customer_id, meeting_id, meeting_url, PM_email_id,
                                                dialin_number,
                                                PM_name)).start()
    else:
        res = response.json()
    return JsonResponse({'success': True, 'data': res})


@api_view(['POST'])
def delete_bookings(request):
    """
    :param request:
    :return:
    """
    res = ""
    d = request.data
    PM_name = ''
    PM_email_id = ''
    #order_id = request.data['orders'][0].get('order_id')
    # if d['orders'] != []:
    #     orders = getObjects('Orders', {'order_id': order_id})
    #     customer_id = orders['records'][0]['customer_id']
    ret = []
    headers = {
        'accept': "application/json",
        'authorization': revio_api_key
    }
    appointment_id = None
    url = "https://restapi.rev.io/v1/Orders?order_id={}".format(d['primary_order'])
    getresponse = requests.request("GET", url, headers=headers)
    orderres = getresponse.json()
    for row in orderres['records'][0]['fields']:
        if row['field_id'] == 108:
            name = row['value'].split(' ')
            PM_name = row['value']
            PM_email_id = name[0][0] + name[1] + '@CallOne.com'
    #ret.append(res)
    for j in orderres['records'][0]['fields']:
        if j['field_id'] == 143:
            appointment_id = j['value']
        if j['field_id'] == 148:
            schedule_id = j['value']
    for j in orderres['records'][0]['fields']:
        if j['field_id'] == 143:
            j['value'] = ''
        if d['datetype'] == 'ttu':
            if j['field_id'] == 131:
                j['value'] = ''
            if j['field_id'] == 126:
                j['value'] = ''
        if d['datetype'] == 'port':
            if j['field_id'] == 122:
                j['value'] = ''
            if j['field_id'] == 123:
                j['value'] = ''
        if j['field_id'] == 148:
            j['value'] = ''
    puturl = "https://restapi.rev.io/v1/Orders/{}".format(d['primary_order'])
    putdata = json.dumps(orderres['records'][0])
    headers = {
        'accept': "application/json",
        'authorization': revio_api_key,
        'content-type': "text/json"
    }
    updateresponse = requests.put(puturl, data=putdata, headers=headers)

    if d['datetype'] == 'ttu':
        task_url = 'https://restapi.rev.io/v1/Tasks?order_id={}&subject=Scheduling Pre-Install and Activation'.format(
            d['primary_order'])
        task_st_update = update_task_status(task_url)
    if d['datetype'] == 'port':
        task_url = 'https://restapi.rev.io/v1/Tasks?order_id={}&subject=Schedule Activation with Service Activation'.format(
            d['primary_order'])
        task_st_update = update_task_status(task_url)
    subjects = ['Schedule Preinstall TTU and PORT Activation with Customer & Service Activations',
                'Schedule Test and Accept']
    for sub in subjects:
        task_url = 'https://restapi.rev.io/v1/Tasks?order_id={}&subject={}'.format(d['primary_order'], sub)
        task_st_update = update_task_status(task_url)

    if orderres['records'][0]['customer_id']:
        customer_id = orderres['records'][0]['customer_id']
        noteurl = "https://restapi.rev.io/v1/Notes"

        headers = {
            'accept': "application/json; charset=utf-8",
            'authorization': revio_api_key,
            'content-type': "text/json"
        }

        note_data = {
            'subject': 'Appointment cancelled in SuperSaaS for appointment id {}'.format(
                appointment_id),
            'body': 'Appointment cancelled in SuperSaaS',
            # .format(
            #     PM_name,
            #     d['schedule_name'],
            #     str(resdate[0]),
            #     meeting_id,
            #     dialin_number),
            'customer_id': customer_id,
            'order_id': d['primary_order'],
            'note_type_id': 1012,
        }
        response = requests.post(noteurl, data=json.dumps(note_data), headers=headers)



    deleteurl = "https://www.supersaas.com/api/bookings/{}.json?schedule_id={}&api_key=bTL8QZmn67kSHMo_1DZlqg".format(appointment_id,d['schedule_id'])
    headers = {
        'accept': "application/json",
        'content-type': "text/json"
    }
    deleteresponse = requests.delete(deleteurl, headers=headers)

    try:
        for i in d['orders']:
            url = "https://restapi.rev.io/v1/Orders?order_id={}".format(i['order_id'])
            getresponse = requests.request("GET", url, headers=headers)
            orderres = getresponse.json()
            try:
                ret.append(res)
                for k in orderres['records'][0]['fields']:
                    if k['field_id'] == 143:
                        rel_appointment_id = k['value']
                    if j['field_id'] == 148:
                        schedule_id = j['value']
                if appointment_id == rel_appointment_id:
                    for j in orderres['records'][0]['fields']:
                        if j['field_id'] == 143:
                            j['value'] = ''
                        if i['datetype'] == 'ttu':
                            if j['field_id'] == 131:
                                j['value'] = ''
                            if j['field_id'] == 126:
                                j['value'] = ''
                        if i['datetype'] == 'port':
                            if j['field_id'] == 122:
                                j['value'] = ''
                            if j['field_id'] == 123:
                                j['value'] = ''
                        if j['field_id'] == 148:
                            j['value'] = ''
                    puturl = "https://restapi.rev.io/v1/Orders/{}".format(i['order_id'])
                    putdata = json.dumps(orderres['records'][0])
                    headers = {
                        'accept': "application/json",
                        'authorization': revio_api_key,
                        'content-type': "text/json"
                    }
                    updateresponse = requests.put(puturl, data=putdata, headers=headers)

                    if i['datetype'] == 'ttu':
                        task_url = 'https://restapi.rev.io/v1/Tasks?order_id={}&subject=Scheduling Pre-Install and Activation'.format(
                            i['order_id'])
                        task_st_update = update_task_status(task_url)
                    if i['datetype'] == 'port':
                        task_url = 'https://restapi.rev.io/v1/Tasks?order_id={}&subject=Schedule Activation with Service Activation'.format(
                            i['order_id'])
                        task_st_update = update_task_status(task_url)
                    subjects = [
                        'Schedule Preinstall TTU and PORT Activation with Customer & Service Activations',
                        'Schedule Test and Accept']
                    for sub in subjects:
                        task_url = 'https://restapi.rev.io/v1/Tasks?order_id={}&subject={}'.format(
                            i['order_id'], sub)
                        task_st_update = update_task_status(task_url)

                    if orderres['records'][0]['customer_id']:
                        customer_id = orderres['records'][0]['customer_id']
                        noteurl = "https://restapi.rev.io/v1/Notes"

                        headers = {
                            'accept': "application/json; charset=utf-8",
                            'authorization': revio_api_key,
                            'content-type': "text/json"
                        }

                        note_data = {
                            'subject': 'Appointment has been cancelled, appointment id {}'.format(
                                appointment_id),
                            'body': 'Appointment has been cancelled',
                            # .format(
                            #     PM_name,
                            #     d['schedule_name'],
                            #     str(resdate[0]),
                            #     meeting_id,
                            #     dialin_number),
                            'customer_id': customer_id,
                            'order_id': i['order_id'],
                        }
                        response = requests.post(noteurl, data=json.dumps(note_data), headers=headers)

                        deleteurl = "https://www.supersaas.com/api/bookings/{}.json?schedule_id={}&api_key=bTL8QZmn67kSHMo_1DZlqg".format(
                            appointment_id, schedule_id)
                        headers = {
                            'accept': "application/json",
                            'content-type': "text/json"
                        }
                        deleteresponse = requests.delete(deleteurl, headers=headers)
            except Exception as e:
                return JsonResponse({'success': False, 'data': str(e)})
    except Exception as e:
        return JsonResponse({'success': False, 'data': str(e)})
    res = 'Successfully Cancelled the appointment'

    threading.Thread(target=techSpecdelete, args=(request, customer_id, PM_email_id, PM_name)).start()

    return JsonResponse({'success': True, 'data': res})


def techSpec(request, customer_id, meeting_id, meeting_url, PM_email_id, dialin_number, PM_name):
    try:
        # import pdb;pdb.set_trace()
        PM_email_id = 'pythonwork2020@gmail.com'
        url = 'http://foersom.com/net/HowTo/data/OoPdfFormExample.pdf'
        r = requests.get(url)
        # filename = url.split('/')[-1]  # this will take only -1 splitted part of the url
        file_name = 'techspec.pdf'
        if os.path.exists("techspec.pdf"):
            os.remove("techspec.pdf")
        with open(file_name, 'wb') as output_file:
            output_file.write(r.content)
        body = 'Hi {}, <br>Please find the below details and PDF in the attachment. <br><br>Meeting Id - {} <br> Meeting Link - <a ' \
               'href= "{}">{} </a><br> Dailin Number - {}. <br><br>Thank you'.format(
            PM_name, meeting_id, meeting_url, meeting_url, dialin_number)

        msg = EmailMessage('Techspec email', body, PM_email_id, [PM_email_id])
        msg.content_subtype = "html"
        msg.attach_file(file_name, 'application/pdf')
        msg.send()
        # os.remove(file_name)
        res = "success"
        return JsonResponse({'success': True, 'data': res})
    except Exception as e:
        return JsonResponse({'success': False, 'data': e})


def techSpecdelete(request,customer_id,PM_email_id,PM_name):
    try:
        # body = 'Hi {}, \n The meeting id is {} and dailin number is {} .Please find the pdf in attachment \nThank you'.format(PM_name,meeting_id,dialin_number)
        body = "appointment has been cancelled"
        PM_email_id = 'pythonwork2020@gmail.com'
        msg = EmailMessage('Techspec email', body, 'pythonwork2020@gmail.com', [PM_email_id])
        msg.content_subtype = "html"
        msg.send()
        res = "success"
        return JsonResponse({'success': True, 'data': res})
    except Exception as e:
        return JsonResponse({'success': False, 'data': res})


def lock_processor(meeting_id):
    today = datetime.today().strftime("%Y%m%d")
    yesterday = datetime.today() - timedelta(days=1)
    yesterday = yesterday.strftime("%Y%m%d")
    filename = 'lock_' + today + '.csv'
    last_filename = 'lock_' + yesterday + '.csv'
    if os.path.exists(filename):
        lock_file = open(filename, 'r')
        lines = lock_file.readlines()
        lock_file.close()
        for line in lines:
            if meeting_id in line:
                return True

        with open(filename, 'a+') as f:
            f.write('\n')
            f.write(meeting_id)
    else:
        with open(filename, 'w') as f:
            f.write('\n')
            f.write(meeting_id)
    try:
        os.remove(last_filename)
    except OSError:
        pass
    return False


def sync_meetings():
    data = pd.read_excel(os.path.join(BASE_DIR, 'meetings.xlsx'), index_col=1)
    df = pd.DataFrame(data, columns=['ID', 'Dial-in', 'URL'])
    for index, row in df.iterrows():
        meeting_id = row["ID"]
        dialin_number = row["Dial-in"]
        url = row["URL"]
        status = lock_processor(meeting_id)
        if not status:
            resp = schedule_meeting(meeting_id,dialin_number,url)
            return resp
    return 'No available meeting for now'


def schedule_meeting(meeting_id,dialin_number,url):
    return [meeting_id,dialin_number,url]


def import_appointments(request):
    data = pd.read_excel(os.path.join(BASE_DIR, 'import_app.xlsx'))
    df = pd.DataFrame(data, columns=['Activator', 'location', 'start', 'end'])
    for index, row in df.iterrows():
        schedule_id = row['Activator']
        techspec = row['Location']
        start = row['Start']
        end = row['End']
        full_name = ''
        description = ''
        url = 'https://www.supersaas.com/api/bookings.json?schedule_id={}&api_key=bTL8QZmn67kSHMo_1DZlqg&booking[start]={}&booking[finish]={}&booking[full_name]={}&booking[description]={}' \
              '&booking[field_1_r]={}&booking[field_2_r]={}'.format(
            schedule_id, start, end, full_name, description, 'In progress', techspec)
        response = requests.request("POST", url)


def update_task_status(task_url):
    headers = {
        'accept': "application/json",
        'authorization': revio_api_key,
        'content-type': "text/json"
    }
    task_response = requests.get(task_url, headers=headers)
    task_res = task_response.text
    task_convacc = json.loads(task_res)
    if task_convacc['record_count'] != 0:
        task_id = task_convacc['records'][0]['task_id']

        task_status_url = 'https://restapi.rev.io/v1/Tasks/{}'.format(task_id)
        task_status_resp = requests.request("GET", task_status_url, headers=headers)
        task_status_resp_json = json.loads(task_status_resp.text)
        if not task_status_resp_json['complete']:
            task_update_url = 'https://restapi.rev.io/v1/Tasks/{}/action'.format(task_id)
            task_data = {"action": "COMPLETE"}
            task_update_response = requests.put(task_update_url, data=json.dumps(task_data), headers=headers)
        elif task_status_resp_json['complete']:
            task_update_url = 'https://restapi.rev.io/v1/Tasks/{}/action'.format(task_id)
            task_data = {"action": "INCOMPLETE"}
            task_update_response = requests.put(task_update_url, data=json.dumps(task_data), headers=headers)
    return True
