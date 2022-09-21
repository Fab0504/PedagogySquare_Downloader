import hashlib
import json
import os
import time
import requests
from contextlib import closing


login_url = r"https://teaching.applysquare.com/Api/User/ajaxLogin"
attachment_url_fmt = r'https://teaching.applysquare.com/Api/CourseAttachment/getList/token/{}?parent_id={}&page={}&plan_id=-1&uid={}&cid={}'
course_info_url_fmt = r'https://teaching.applysquare.com/Api/Public/getIndexCourseList/token/{}?type=1&usertype=1&uid={}'
attachment_detail_url_fmt = r'https://teaching.applysquare.com/Api/CourseAttachment/ajaxGetInfo/token/{}?id={}&uid={}&cid={}'


# Get Hex-md5 encoded password
def hex_md5_stringify(raw_str: str):
    md5_encoder = hashlib.md5()
    md5_encoder.update(str(raw_str).encode('utf-8'))
    return md5_encoder.hexdigest()


# Function dealing with illegal characters of windows filename
def filename_filter(name: str):
    illegal_list = list(r'/\:*?”"<>|')
    for char in illegal_list:
        name = name.replace(char, '_')
    return name


def construct_attachment_list(sess, token, pid, uid, cid):
    attachment_list = list()
    attachment_info_url = attachment_url_fmt.format(token, pid, 1, uid, cid)
    r = sess.get(attachment_info_url)
    info = r.json()['message']
    file_num = info.get('count')

    current_page = 1
    # Add attachment path to attachment_list
    while len(attachment_list) < file_num:
        current_url = attachment_url_fmt.format(token, pid, current_page, uid, cid)
        r = sess.get(current_url)
        info = r.json()['message']
        attachment_list.extend(info.get('list'))
        current_page += 1
    return attachment_list

def main():
    # Load config from config.json
    with open('config.json', 'r') as f:
        config = json.loads(f.read())
        user_name = config.get('username')
        user_passwd = config.get('password')

        download_all_cid = config.get('download_all_cid')
        cid_certain_list = config.get('cid_certain_list')
        cid_expel_list = config.get('cid_expel_list')

        download_all_ext = config.get('download_all_ext')
        ext_certain_list = config.get('ext_certain_list')
        ext_expel_list = config.get('ext_expel_list')

        download_all_filename = config.get('download_all_filename')
        filename_certain_list = config.get('filename_certain_list')
        filename_expel_list = config.get('filename_expel_list')

    sess = requests.Session()

    # login
    print("login, wait ...")
    login_request = sess.post(login_url, data={"email": user_name, "password": hex_md5_stringify(user_passwd)})
    login_response = login_request.json()
    login_info = login_response['message']
    token = login_info['token']
    uid = login_info['uid']
    print("login successfully")

    cid2name_dict = dict()  # cid2name_dict = {cid: course_name}
    course_info_url = course_info_url_fmt.format(token, uid)
    r = sess.get(course_info_url)
    info = r.json()["message"]

    for entry in info:
        cid2name_dict[entry.get('cid')] = entry.get('name')

    if download_all_cid:
        cid_download_list = cid2name_dict.keys()
    elif len(cid_certain_list):
        cid_download_list = [str(x) for x in cid_certain_list]
        for cid in cid_certain_list:
            if not str(cid) in cid2name_dict.keys():
                print(f"can't find course with cid {cid}")
                cid_download_list.remove(str(cid))
    elif len(cid_expel_list):
        cid_download_list = cid2name_dict.keys()
        for cid in cid_expel_list:
            if str(cid) in cid_download_list:
                cid_download_list.remove(str(cid))
    else:
        cid_download_list = list()

    cwd = os.getcwd()
    download_dir = "D:/download_backup/edge_download/pedagogysquare_download"
    for cid in cid_download_list:
        course_name = filename_filter(cid2name_dict[cid])
        print("downloading files of course {}".format(course_name))

        # create dir -> enter dir
        download_course_dir = os.path.join(download_dir, course_name)
        try:
            os.chdir(download_course_dir)
        except FileNotFoundError:
            os.makedirs(download_course_dir, exist_ok=True)
            os.chdir(download_course_dir)

        course_attachment_list = construct_attachment_list(sess=sess, token=token, pid=0, uid=uid, cid=cid)

        # Iteratively add files in dirs to global attachment list
        dir_counter = 0
        for entry in course_attachment_list:
            if entry.get('ext') == 'dir':
                dir_counter += 1
                dir_id = entry.get('id')
                course_attachment_list.extend(
                    construct_attachment_list(sess=sess, token=token, pid=dir_id, uid=uid, cid=cid))

        # num_files, num_dirs
        file_counter = len(course_attachment_list) - dir_counter
        print(f"get {file_counter} files, with {dir_counter} dirs")

        for entry in course_attachment_list:
            # get ext and filename
            ext = entry.get('ext')
            if ext in entry.get('title'):
                filename = filename_filter(entry.get('title'))
            else:
                filename = filename_filter("{}.{}".format(entry.get('title'), ext))

            if ext == 'dir':
                continue

            if not download_all_ext:
                if ext not in ext_certain_list or ext in ext_expel_list:
                    continue

            if not download_all_filename:
                if any([x for x in filename_expel_list if x in filename]) or \
                        not any([x for x in filename_certain_list if x in filename]):
                    continue

            filesize = entry.get('size')

            # Get download url for un-downloadable files
            if entry.get('can_download') == '0':
                attachment_detail_url = attachment_detail_url_fmt.format(token, entry.get('id'), uid, cid)
                r = sess.get(attachment_detail_url)
                info = r.json()['message']
                entry['path'] = info.get('path')

            with closing(requests.get(entry.get('path').replace('amp;', ''), stream=True)) as res:

                try:
                    content_size = eval(res.headers['content-length'])
                except:
                    print("Failed to get content length of file {}, please download it manually.".format(filename))
                    continue

                if filename in os.listdir():
                    if os.path.getsize(filename) == content_size:
                        print("File \"{}\" is up-to-date".format(filename))
                        continue
                    else:
                        print("Updating File {}".format(filename))
                        os.remove(filename)

                print("Downloading {}, filesize = {}".format(filename, filesize))
                chunk_size = min(content_size, 10240)
                with open(filename, "wb") as f:
                    chunk_count = 0
                    start_time = time.time()
                    total = content_size / 1024 / 1024
                    for data in res.iter_content(chunk_size=chunk_size):
                        chunk_count += 1
                        processed = len(data) * chunk_count / 1024 / 1024
                        current_time = time.time()
                        if chunk_count < 5:
                            print(r"Total: {:.2f} MB  Processed: {:.2f} MB ({:.2f}%)".
                                  format(total, processed, processed / total * 100), end='\r')
                        else:
                            remaining = (current_time - start_time) / processed * (total - processed)
                            print(r"Total: {:.2f} MB  Processed: {:.2f} MB ({:.2f}%), ETA {:.2f}s".
                                  format(total, processed, processed / total * 100, remaining), end='\r')
                        f.write(data)
        os.chdir(cwd)
    print("done")

if __name__=="__main__":
    main()