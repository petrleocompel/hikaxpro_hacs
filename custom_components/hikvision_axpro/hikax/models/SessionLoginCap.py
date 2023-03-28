class SessionLoginCap:
    def __init__(self, session_id, challenge, salt, salt2, is_irreversible, iteration):
        self.sessionID = session_id
        self.challenge = challenge
        self.salt = salt
        self.salt2 = salt2
        self.is_irreversible = is_irreversible
        self.iteration = iteration
