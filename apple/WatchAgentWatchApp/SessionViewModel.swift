import Foundation
import Combine

extension Notification.Name {
    static let triggerSkill = Notification.Name("triggerSkill")
}

@MainActor
final class SessionViewModel: ObservableObject {
    @Published var transcript = ""
    @Published var latestSpeech = "准备就绪，可说\u{201C}今日日程\u{201D}、\u{201C}工作进展\u{201D}、\u{201C}查看快递\u{201D}或\u{201C}健康管理\u{201D}。"
    @Published var cards: [ActionCard] = []
    @Published var streamLines: [String] = []
    @Published var isListening = false
    @Published var autoListenOnLaunch = true
    @Published var errorText: String?
    @Published private(set) var codexQueueTotal = 0
    @Published private(set) var codexQueueHandled = 0
    @Published private(set) var rejectDecisionCardId: String?

    let sessionId = UUID().uuidString

    private let apiClient: WatchAgentAPIClient
    private let relayClient: WatchRelayClient
    private let speechController: SpeechController
    private let voiceEngine: VoicePromptEngine
    private let healthProvider = HealthDataProvider()
    private let weatherProvider = WeatherDataProvider()

    private var pendingRejectToken: String?
    private var eventPollingTask: Task<Void, Never>?
    private var latestEventId = 0
    private var skillNotificationObserver: Any?
    private var speechDiagCancellable: AnyCancellable?

    var relayConnected: Bool { relayClient.isReachable }
    @Published var speechDiag: String = ""
    var currentCard: ActionCard? { cards.first }
    var pendingCardCount: Int { cards.count }
    var isOnCodexApprovalCard: Bool { currentCard?.isVoiceRejectOnly == true }
    var codexProgressLabel: String? {
        guard isOnCodexApprovalCard, codexQueueTotal > 0 else { return nil }
        let current = min(codexQueueHandled + 1, codexQueueTotal)
        return "第\(current)/\(codexQueueTotal)条"
    }
    var codexThreadLabel: String? {
        currentCard?.acpThreadId.map { "Thread: \($0)" }
    }
    var codexSessionLabel: String? {
        currentCard?.openclawSessionId.map { "OpenClaw: \($0)" }
    }

    func isRejectDecisionActive(for card: ActionCard) -> Bool {
        rejectDecisionCardId == card.cardId
    }

    init(
        apiClient: WatchAgentAPIClient,
        relayClient: WatchRelayClient? = nil,
        speechController: SpeechController? = nil,
        voiceEngine: VoicePromptEngine? = nil
    ) {
        self.apiClient = apiClient
        self.relayClient = relayClient ?? WatchRelayClient()
        self.speechController = speechController ?? SpeechController()
        let engine = voiceEngine ?? VoicePromptEngine()
        engine.relayClient = self.relayClient
        self.voiceEngine = engine

        speechDiagCancellable = self.speechController.$diagInfo
            .receive(on: DispatchQueue.main)
            .assign(to: \.speechDiag, on: self)

        // Listen for Siri/Shortcut-triggered skills
        skillNotificationObserver = NotificationCenter.default.addObserver(
            forName: .triggerSkill,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            guard let hint = notification.object as? String else { return }
            Task { @MainActor [weak self] in
                self?.triggerByHint(hint, entryMode: .siri)
            }
        }
    }

    deinit {
        if let observer = skillNotificationObserver {
            NotificationCenter.default.removeObserver(observer)
        }
    }

    static var preview: SessionViewModel {
        SessionViewModel(apiClient: WatchAgentAPIClient(baseURL: URL(string: "http://127.0.0.1:8787")!))
    }

    func handleLaunch() {
        relayClient.activate()
        Task { _ = await healthProvider.requestAuthorization() }
        weatherProvider.requestAuthorization()
        guard autoListenOnLaunch else { return }
        Task { @MainActor in await startListening() }
    }

    /// Called every time the app returns to the foreground (scenePhase → .active).
    func handleForeground() {
        guard autoListenOnLaunch, !isListening, eventPollingTask == nil else { return }
        Task { @MainActor in await startListening() }
    }

    /// Called when app moves to background/inactive — stop any in-progress capture.
    func handleBackground() {
        guard isListening else { return }
        speechController.stopCapture()
        isListening = false
    }

    func trigger(skill: QuickSkill, entryMode: EntryMode = .complication) {
        Task { @MainActor in
            let healthSnapshot = await fetchHealthSnapshotIfNeeded(hint: skill.hint)
            let coords = await fetchCoordinatesIfNeeded(hint: skill.hint)
            await sendCommand(
                utterance: skill.spokenCommand,
                skillHint: skill.hint,
                entryMode: entryMode,
                intentId: "intent-\(skill.hint)",
                healthSnapshot: healthSnapshot,
                latitude: coords?.0,
                longitude: coords?.1
            )
        }
    }

    func triggerByHint(_ hint: String, entryMode: EntryMode = .siri) {
        if let skill = QuickSkill.allCases.first(where: { $0.hint == hint }) {
            trigger(skill: skill, entryMode: entryMode)
        }
    }

    func triggerFromSiriMorningBrief() {
        trigger(skill: .morningBrief, entryMode: .siri)
    }

    /// Start voice input directly via SFSpeechRecognizer
    func presentDictation() {
        Task { @MainActor in await startListening() }
    }

    func startListening() async {
        errorText = nil
        transcript = ""
        let granted = await speechController.requestPermission()
        guard granted else {
            errorText = "语音不可用，请在系统中允许麦克风并启用听写。"
            return
        }

        do {
            try speechController.startCapture(onPartial: { [weak self] text in
                Task { @MainActor in
                    self?.transcript = text
                }
            }, onFinal: { [weak self] text in
                Task { @MainActor in
                    self?.transcript = text
                    self?.stopListeningAndSend()
                }
            })
            isListening = true
        } catch {
            errorText = "语音启动失败：\(error.localizedDescription)"
        }
    }

    func stopListeningAndSend() {
        speechController.stopCapture()
        isListening = false

        // Prefer live transcript; fall back to last captured result from recognizer
        let raw = transcript.isEmpty ? speechController.lastTranscript : transcript
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        transcript = ""
        guard !text.isEmpty else { return }

        if let rejectToken = pendingRejectToken {
            pendingRejectToken = nil
            Task { @MainActor in
                await sendConfirmation(
                    token: rejectToken,
                    decision: .reject,
                    mode: .voice,
                    followupText: text
                )
            }
            return
        }

        Task { @MainActor in
            await sendCommand(utterance: text, skillHint: nil, entryMode: .tap, intentId: nil, healthSnapshot: nil, latitude: nil, longitude: nil)
        }
    }

    func approve(card: ActionCard, mode: InputMode = .gesture) {
        guard let token = card.confirmToken else { return }
        Task { @MainActor in
            await sendConfirmation(token: token, decision: .approve, mode: mode, followupText: nil)
        }
    }

    func beginRejectDecision(card: ActionCard) {
        guard card.confirmToken != nil else { return }
        rejectDecisionCardId = card.cardId
        latestSpeech = "请选择拒绝方式：直接拒绝，或语音补充。"
        voiceEngine.speak(latestSpeech)
    }

    func rejectWithoutFollowup(card: ActionCard) {
        guard let token = card.confirmToken else { return }
        rejectDecisionCardId = nil
        Task { @MainActor in
            await sendConfirmation(token: token, decision: .reject, mode: .tap, followupText: nil)
        }
    }

    func rejectWithVoiceFollowup(card: ActionCard) {
        guard let token = card.confirmToken else { return }
        rejectDecisionCardId = nil
        pendingRejectToken = token
        latestSpeech = "请说补充指令，例如：No, and do ..."
        voiceEngine.speak(latestSpeech)
        Task { @MainActor in
            await startListening()
        }
    }

    // MARK: - Private

    private func fetchHealthSnapshotIfNeeded(hint: String) async -> HealthSnapshotPayload? {
        guard hint == "health_manager" else { return nil }
        let snap = await healthProvider.fetchSnapshot()
        return HealthSnapshotPayload(
            heartRate: snap.heartRate,
            restingHeartRate: snap.restingHeartRate,
            steps: snap.steps,
            activeCalories: snap.activeCalories,
            bloodOxygen: snap.bloodOxygen,
            sleepHours: snap.sleepHours,
            sleepDeepMinutes: snap.sleepDeepMinutes,
            sleepRemMinutes: snap.sleepRemMinutes
        )
    }

    private func fetchCoordinatesIfNeeded(hint: String) async -> (Double, Double)? {
        return await weatherProvider.fetchCoordinates()
    }

    private func sendCommand(
        utterance: String,
        skillHint: String?,
        entryMode: EntryMode,
        intentId: String?,
        healthSnapshot: HealthSnapshotPayload?,
        latitude: Double?,
        longitude: Double?
    ) async {
        if isListening {
            speechController.stopCapture()
            isListening = false
        }
        voiceEngine.stopAll()
        eventPollingTask?.cancel()   // immediately truncate old task to prevent rebound
        eventPollingTask = nil
        errorText = nil
        latestSpeech = ""
        streamLines = []
        do {
            let reply = try await relayClient.sendCommand(
                sessionId: sessionId,
                utterance: utterance,
                skillHint: skillHint,
                entryMode: entryMode,
                intentId: intentId,
                latitude: latitude,
                longitude: longitude
            )
            applyWatchReply(reply)
        } catch WatchRelayClient.RelayError.notReachable {
            errorText = "iPhone relay 未连接。请打开 PhoneBridgeApp 并点 Start Relay。"
        } catch WatchRelayClient.RelayError.notSupported {
            errorText = "此设备不支持 WatchConnectivity。"
        } catch WatchRelayClient.RelayError.malformedResponse {
            errorText = "Relay 响应格式错误。"
        } catch WatchRelayClient.RelayError.timeout {
            errorText = "Relay 超时（30s）。iPhone 收到请求了吗？检查 PhoneBridgeApp 的 Last Event。"
        } catch {
            let nsError = error as NSError
            errorText = "[\(nsError.domain) \(nsError.code)] \(nsError.localizedDescription)"
            print("[WATCH DEBUG] sendCommand error: domain=\(nsError.domain) code=\(nsError.code) info=\(nsError.userInfo)")
        }
    }

    private func sendConfirmation(
        token: String,
        decision: Decision,
        mode: InputMode,
        followupText: String?
    ) async {
        do {
            let reply = try await relayClient.sendConfirmation(
                sessionId: sessionId,
                token: token,
                decision: decision,
                followupText: followupText
            )
            applyConfirmReply(reply, token: token)
        } catch {
            errorText = "确认失败：\(error.localizedDescription)"
        }
    }

    private func applyWatchReply(_ reply: WatchReply) {
        if reply.debug?.skillRunId != nil {
            codexQueueTotal = 0
            codexQueueHandled = 0
        }
        rejectDecisionCardId = nil
        latestSpeech = reply.speechText
        cards = reply.cards
        voiceEngine.speak(reply.speechText)

        if reply.debug?.skillRunId != nil {
            startEventPolling()
        }
    }

    private func applyConfirmReply(_ reply: WatchConfirmResponse, token: String) {
        if let removedCard = cards.first(where: { $0.confirmToken == token }), removedCard.isVoiceRejectOnly {
            codexQueueHandled += 1
        }
        if let card = cards.first(where: { $0.confirmToken == token }), rejectDecisionCardId == card.cardId {
            rejectDecisionCardId = nil
        }
        latestSpeech = reply.speechText
        cards.removeAll { $0.confirmToken == token }
        voiceEngine.speak(reply.speechText)
        speakNextCardPromptIfNeeded()
    }

    private var runCompleted = false

    private func startEventPolling() {
        eventPollingTask?.cancel()
        latestEventId = 0
        runCompleted = false

        eventPollingTask = Task { @MainActor [weak self] in
            guard let self else { return }
            var idleRounds = 0
            for _ in 0 ..< 40 {
                if Task.isCancelled || runCompleted { return }
                do {
                    let response = try await relayClient.fetchEvents(sessionId: sessionId, afterEventId: latestEventId, limit: 50)
                    if response.events.isEmpty {
                        idleRounds += 1
                        // ~50 rounds × 300ms ≈ 15s between progress nudges
                        if idleRounds > 0 && idleRounds % 50 == 0 {
                            let msg = "还在处理中，请稍候…"
                            latestSpeech = msg
                            voiceEngine.speak(msg)
                        }
                    } else {
                        idleRounds = 0
                        for event in response.events {
                            latestEventId = max(latestEventId, event.eventId)
                            consume(event: event)
                        }
                    }
                } catch {
                    errorText = "增量事件拉取失败：\(error.localizedDescription)"
                    return
                }
                if runCompleted { return }
                try? await Task.sleep(nanoseconds: 300_000_000)
            }
        }
    }

    private func consume(event: SkillStreamEvent) {
        // Final speech from LLM agent — display only, don't speak (tool_results already spoken)
        if event.eventType == "final_speech",
           let speech = event.payload["speech_text"]?.value as? String {
            latestSpeech = speech
        }

        if let summary = event.payload["summary"]?.value as? String {
            streamLines.append(summary)
            latestSpeech = summary
            voiceEngine.speak(summary)
        }

        // Stop polling once the backend signals run completion
        if event.eventType == "run_completed" {
            runCompleted = true
            return
        }

        guard let rawCards = event.payload["cards"]?.value else { return }
        guard let cardsArray = rawCards as? [Any] else { return }
        guard let data = try? JSONSerialization.data(withJSONObject: cardsArray) else { return }

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        if let decoded = try? decoder.decode([ActionCard].self, from: data) {
            registerIncomingCodexCards(decoded)
            cards.append(contentsOf: decoded)
        }
    }

    private func speakNextCardPromptIfNeeded() {
        guard let next = currentCard, next.isVoiceRejectOnly else { return }
        let threadHint = next.acpThreadId.map { "线程 \($0)。" } ?? ""
        let progressHint = codexProgressLabel.map { "\($0)。" } ?? ""
        let prompt = "下一条待审批：\(next.title)。\(progressHint)\(threadHint)Double Tap 同意，或点击 No 选择直接拒绝/语音补充。"
        latestSpeech = prompt
        voiceEngine.speak(prompt)
    }

    private func registerIncomingCodexCards(_ newCards: [ActionCard]) {
        let newCodexCount = newCards.filter { $0.isVoiceRejectOnly }.count
        guard newCodexCount > 0 else { return }
        codexQueueTotal += newCodexCount
    }
}
