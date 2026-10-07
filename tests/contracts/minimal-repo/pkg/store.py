class Record:
    key = 0


class Row(Record):
    def save(self):
        return self.key


def save(value):
    return value
