import Foundation
import WatchConnectivity

final class WatchRelayClient: NSObject, @unchecked Sendable, @preconcurrency WCSessionDelegate {
    enum RelayError: Error {
        case notSupported
        case notReachable
        case malformedResponse
        case timeout
    }

    private let decoder: JSONDecoder

    override init() {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        self.decoder = decoder
        super.init()
    }

    var isReachable: Bool {
        WCSession.isSupported() && WCSession.default.isReachable
    }

    func activate() {
        guard WCSession.isSupported() else { return }
        let session = WCSession.default
        session.delegate = self
        session.activate()
    }

    func sendCommand(
        sessionId: String,
        utterance: String,
        skillHint: String?,
        entryMode: EntryMode,
        intentId: String?,
        latitude: Double? = nil,
        longitude: Double? = nil
    ) async throws -> WatchReply {
        var message: [String: Any] = [
            "kind": "command",
            "session_id": sessionId,
            "utterance": utterance,
            "entry_mode": entryMode.rawValue,
        ]
        if let skillHint {
            message["skill_hint"] = skillHint
        }
        if let intentId {
            message["intent_id"] = intentId
        }
        if let latitude {
            message["latitude"] = latitude
        }
        if let longitude {
            message["longitude"] = longitude
        }
        return try await sendMessage(message)
    }

    func fetchEvents(sessionId: String, afterEventId: Int, limit: Int) async throws -> SkillEventsResponse {
        let message: [String: Any] = [
            "kind": "get_events",
            "session_id": sessionId,
            "after_event_id": afterEventId,
            "limit": limit,
        ]
        return try await sendMessage(message)
    }

    func requestTTS(text: String, voiceType: String, speedRatio: Double) async throws -> Data {
        let message: [String: Any] = [
            "kind": "tts",
            "text": text,
            "voice_type": voiceType,
            "speed_ratio": speedRatio,
        ]
        let reply: [String: Any] = try await sendMessageRaw(message)
        guard let base64String = reply["audio_base64"] as? String,
              let audioData = Data(base64Encoded: base64String) else {
            throw RelayError.malformedResponse
        }
        return audioData
    }

    func sendConfirmation(
        sessionId: String,
        token: String,
        decision: Decision,
        followupText: String?
    ) async throws -> WatchConfirmResponse {
        var message: [String: Any] = [
            "kind": "confirm",
            "session_id": sessionId,
            "confirm_token": token,
            "decision": decision.rawValue,
        ]
        if let followupText {
            message["followup_text"] = followupText
        }
        return try await sendMessage(message)
    }

    private func sendMessage<T: Decodable & Sendable>(_ message: [String: Any]) async throws -> T {
        guard WCSession.isSupported() else {
            throw RelayError.notSupported
        }
        let session = WCSession.default
        guard session.isReachable else {
            throw RelayError.notReachable
        }

        return try await withThrowingTaskGroup(of: T.self) { group in
            group.addTask { [weak self] in
                guard let self else { throw RelayError.malformedResponse }
                return try await withCheckedThrowingContinuation { continuation in
                    let lock = NSLock()
                    var didResume = false
                    func tryResume(with result: Result<T, Error>) {
                        lock.lock()
                        defer { lock.unlock() }
                        guard !didResume else { return }
                        didResume = true
                        continuation.resume(with: result)
                    }
                    session.sendMessage(message) { reply in
                        if let errMsg = reply["error"] as? String {
                            tryResume(with: .failure(NSError(
                                domain: "RelayRemote",
                                code: -1,
                                userInfo: [NSLocalizedDescriptionKey: errMsg]
                            )))
                            return
                        }
                        do {
                            let data = try JSONSerialization.data(withJSONObject: reply)
                            let decoded = try self.decoder.decode(T.self, from: data)
                            tryResume(with: .success(decoded))
                        } catch {
                            tryResume(with: .failure(error))
                        }
                    } errorHandler: { error in
                        tryResume(with: .failure(error))
                    }
                }
            }
            group.addTask {
                try await Task.sleep(nanoseconds: 30_000_000_000)
                throw RelayError.timeout
            }
            let result = try await group.next()!
            group.cancelAll()
            return result
        }
    }

    /// Send a WC message and return the raw reply dictionary (for non-Decodable responses like TTS).
    private func sendMessageRaw(_ message: [String: Any]) async throws -> [String: Any] {
        guard WCSession.isSupported() else {
            throw RelayError.notSupported
        }
        let session = WCSession.default
        guard session.isReachable else {
            throw RelayError.notReachable
        }

        return try await withThrowingTaskGroup(of: [String: Any].self) { group in
            group.addTask {
                try await withCheckedThrowingContinuation { continuation in
                    let lock = NSLock()
                    var didResume = false
                    func tryResume(with result: Result<[String: Any], Error>) {
                        lock.lock()
                        defer { lock.unlock() }
                        guard !didResume else { return }
                        didResume = true
                        continuation.resume(with: result)
                    }
                    session.sendMessage(message) { reply in
                        if let errMsg = reply["error"] as? String {
                            tryResume(with: .failure(NSError(
                                domain: "RelayRemote",
                                code: -1,
                                userInfo: [NSLocalizedDescriptionKey: errMsg]
                            )))
                            return
                        }
                        tryResume(with: .success(reply))
                    } errorHandler: { error in
                        tryResume(with: .failure(error))
                    }
                }
            }
            group.addTask {
                try await Task.sleep(nanoseconds: 30_000_000_000)
                throw RelayError.timeout
            }
            let result = try await group.next()!
            group.cancelAll()
            return result
        }
    }

    // MARK: - WCSessionDelegate

    func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        _ = session
        _ = activationState
        _ = error
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        _ = session
    }
}
