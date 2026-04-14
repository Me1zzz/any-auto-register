import random
import string


def generate_string(PREFIX, SUFFIX, MIDDLE_LENGTH=8) -> str:
    middle = ''.join(random.choices(string.ascii_lowercase + string.digits, k=MIDDLE_LENGTH))
    return f"{PREFIX}{middle}{SUFFIX}"


if __name__ == "__main__":
    for _ in range(2):
        print(generate_string("msiabc.", "@manyme.com", random.randint(3, 6)))
        # print(generate_string("", "@fst.cxwsss.online", random.randint(3, 6)))