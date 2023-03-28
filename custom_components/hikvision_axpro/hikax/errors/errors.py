class IncorrectResponseContentError(Exception):
    def __init__(self):
        super().__init__("Response content is not in expected form.")    


class UnexpectedResponseCodeError(Exception):
    def __init__(self, response_code, response_text):
        super().__init__(f"Unexpected response status code {response_code} returned with message {response_text}")