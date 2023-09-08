
class TaskNotExist(Exception):

    def __init__(self, tid):
        super().__init__('Task %s does not exist' % tid)

class TaskWasExisted(Exception):

    def __init__(self, tid):
        self.tid = tid
        super().__init__('Task %s was existed on system' % tid)

class TaskListWasExisted(Exception):

    def __init__(self, tasks):
        self.tasks = tasks
        super().__init__('Tasks was existed on system')

