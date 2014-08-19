#!/usr/bin/python -tt

from __future__ import print_function
import re
import os
import requests
import json
import argparse
from ConfigParser import SafeConfigParser

DEFAULT_DICT = {
    "trac": {
        "user": "anonymous",
        "password": "johndoe",
        "url": "http://localhost/trac"
    },
    "icescrum": {
        "user": "anonymous",
        "password": "johndoe",
        "url": "http://localhost/icescrum",
        "project": "PRJ1",
        "color": "blue"
    }
}

STORY_STATE = { 1: "suggested (sandbox)",
                2: "accepted (backlog)",
                3: "estimated (backlog)",
                4: "planned (sprint)",
                5: "in progress (sprint)",
                7: "done (sprint)" }

class Trac2Icescrum(object):
    """
        Read Trac tickets and put them on Icescrum / take them / ...
    """
    hdr = { "Accept": "application/json" }

    def __init__(self, configfile=None):
        """ read config when creating instance 
            params: configfile = None 
            If configfile is not provided, try to read config from ~/.local/trac2icescrum.ini
        """
        if configfile is None:
            configfile = os.path.abspath( os.getenv("HOME") + "/.local/trac2icescrum.ini")
        self.config = self._readconfig(configfile)
        self._trac = dict(self.config.items('trac'))
        self._icescrum = dict(self.config.items('icescrum'))

    def _readconfig(self, configfile):
        """ fill our config object, if not available, fill it with dummy parameters"""
        config = SafeConfigParser()
        if os.path.isfile(configfile):
            config.readfp(open(configfile, 'r'))
        else:
            for key in DEFAULT_DICT.iterkeys():
                config.add_section(key)
                for opt, val in DEFAULT_DICT[key].items():
                    config.set(key, opt, val)
            config.write(open(configfile, "w"))
            print("Creating %s" % configfile)
            print("A default configuration file has been created, please update it")
        return config

    def trac(self, ticket):
        """ retrieve ticket and description from trac using standart HTTP
            Version tested: Trac 1.0.1 and  Trac 0.1.10(?) with basic / digest auth
        """
        session = requests.Session()

        # first step, ask index to create session
        ret = session.get(self._trac['url'])

        # try to login
        ret = session.get( "%s/login" % self._trac['url'],
            auth=(self._trac['user'], self._trac['password'])
        )

        # get ticket
        ret = session.get("%s/ticket/%s" % (self._trac['url'], ticket))
        if ret.status_code == 404:
            raise Exception("Ticket is not available")

        content = self.parse(ret.content)
        if content[0] != ticket:
            raise Exception("Ticket is not equal")
        return content


    def parse(self, data):
        """ parse content and retrieve ticket and description """
        data = re.sub( r'\s\s+', ' ', data)
        data = re.sub( '\n', '', data)
        data = re.search(r'<title> #(\d+) \((.*)\).*</title>', data)
        if data is None:
            raise Exception("Fail to extract content of ticket")
        title = data.group(1).strip("\n ")
        descr = data.group(2).strip("\n ")
        return [title, descr]

    def getstories(self):
        """
            retrieve all stories opened for project
        """
        url = "%s/ws/p/%s/story" % (self._icescrum['url'], self._icescrum['project'])
        ret = requests.get(url, headers=self.hdr, auth=(self._icescrum['user'], self._icescrum['password']))
        if ret.status_code == 503:
            raise Exception("Webservice is not enabled on Icescrum")
        if ret.status_code//100 != 2:
            raise Exception("Something has failed : %d - %s" % ret.content)
        data = json.loads(ret.content)
        return data

    def icescrum(self, content, story_selected, color=None):
        """
            create a task on icescrum

        """
        if color is None:
            color = self._icescrum['color']

        data = self.getstories()
        # check that story is in progress
        found = False
        # add special stories
        open_story = ["recurrent", "urgent"]
        sprint_id = None
        for story in data:
            if story["state"] == 5:
                open_story.append(story)
                sprint_id = story['parentSprint']['id']
                if story['id'] == story_selected or story['name'] == story_selected:
                    _story = story
                    found = True

        if story_selected in ['recurrent', 'urgent']:
            found = True
            _story = story_selected

        if found is False:
            print("Story not found")
            story_selected = None

        # no story selected or story not found, display stories in progress
        if story_selected is None:
            print("Opened stories :")
            for story in open_story:
                if "id" in story:
                    print("%25s : %s (sprint id:%s)" % (story['name'], STORY_STATE[story["state"]], story['parentSprint']['id']))
                else:
                    print("%25s" % story)
            return

        # create a task
        url = "%s/ws/p/%s/task" % (self._icescrum['url'], self._icescrum['project'])
        task = { "task": {
                "sprint": {"id": sprint_id},
                "name": "#%s %s" % (content[0], content[1]),
                "description": content[1],
                "color": color
            }
        }

        if 'id' in _story:
            task["task"]["parentStory"] = {"id": _story['id']}
        else:
            task["task"]["type"] = _story # for recurent or urgent

        ret = requests.post(url, headers=self.hdr,
            auth=(self._icescrum['user'],
            self._icescrum['password']),
            data=json.dumps(task))

        if ret.status_code != 201:
            print(ret)
            print(ret.status_code)
            print(ret.content)
            raise Exception("Fail to create task")

        print("Task created")
        data = json.loads(ret.content)
        print(json.dumps(data, indent=4))
        return data['id']

    def take_task(self, taskid):
        """ take task """
        url = "%s/ws/p/%s/task/%s/take" % (
            self._icescrum['url'], self._icescrum['project'], taskid)
        ret = requests.post(url, headers=self.hdr,
            auth=(self._icescrum['user'],
            self._icescrum['password']))
        if ret.status_code != 200:
            print(ret)
            print(ret.status_code)
            print(ret.content)
            raise Exception("Fail to take task")
        return True


def main():
    """
    """
    job = Trac2Icescrum()

    parser = argparse.ArgumentParser(
        description='Take a ticket from Trac and push it to Icescrum')
    parser.add_argument('--story', default=None, help="Story to use, if none is specified, list all opened stories")
    parser.add_argument('--color', default=None, help="Specify to use, override default one")
    parser.add_argument('--take',  default=False, action='store_true', 
        help="After creating ticket, take ticket")
    parser.add_argument('ticket', help="ticket number on trac")
    opts = parser.parse_args()

    content = job.trac(opts.ticket)
    taskid = job.icescrum(content=content, story_selected=opts.story, color=opts.color)
    if taskid is not None and opts.take:
        job.take_task(taskid)


if __name__ == "__main__":
    main()
