import Foundation

@MainActor
final class BridgeViewModel: ObservableObject {
    @Published var backendURLString: String {
        didSet {
            UserDefaults.standard.set(backendURLString, forKey: "backendURL")
            backendURL = URL(string: backendURLString) ?? backendURL
        }
    }
    @Published var backendURL: URL
    @Published var sessionState = "inactive"
    @Published var lastEvent = "none"

    @Published var mirrorSessionId = "demo-morning-001"
    @Published var mirrorLines: [String] = []

    private var relay: WCRelayManager?
    private var mirrorTask: Task<Void, Never>?
    private var lastEventId = 0

    init() {
        let saved = UserDefaults.standard.string(forKey: "backendURL") ?? ""
        let url = URL(string: saved) ?? URL(string: "https://")!
        self.backendURLString = saved
        self.backendURL = url
        startRelay()
    }

    func startRelay() {
        relay = WCRelayManager(baseURL: backendURL) { [weak self] state, event in
            Task { @MainActor in
                self?.sessionState = state
                self?.lastEvent = event
            }
        }
        relay?.activate()
    }

    func stopRelay() {
        relay?.deactivate()
        relay = nil
        sessionState = "inactive"
        lastEvent = "relay stopped"
        // Re-register delegate immediately so Watch messages are never dropped
        startRelay()
    }

    func startMirror() {
        stopMirror()
        mirrorLines.removeAll()
        lastEventId = 0
        let client = WatchAgentAPIClient(baseURL: backendURL)

        mirrorTask = Task {
            for _ in 0 ..< 120 {
                if Task.isCancelled { return }
                do {
                    let response = try await client.fetchSkillEvents(
                        sessionId: mirrorSessionId,
                        afterEventId: lastEventId,
                        limit: 100
                    )
                    for event in response.events {
                        lastEventId = max(lastEventId, event.eventId)
                        if let summary = event.payload["summary"]?.value as? String {
                            mirrorLines.append(summary)
                            lastEvent = summary
                        }
                    }
                } catch {
                    lastEvent = "mirror error: \(error.localizedDescription)"
                    return
                }

                try? await Task.sleep(nanoseconds: 400_000_000)
            }
        }
    }

    func stopMirror() {
        mirrorTask?.cancel()
        mirrorTask = nil
    }
}
