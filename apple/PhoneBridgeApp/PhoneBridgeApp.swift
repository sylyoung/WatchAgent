import SwiftUI

@main
struct PhoneBridgeApp: App {
    @StateObject private var vm = BridgeViewModel()

    var body: some Scene {
        WindowGroup {
            NavigationStack {
                List {
                    Section("Bridge Status") {
                        TextField("Backend URL", text: $vm.backendURLString)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                            .onSubmit { vm.startRelay() }
                        LabeledContent("WCSession", value: vm.sessionState)
                        LabeledContent("Last Event", value: vm.lastEvent)
                    }

                    Section("Mirror Session") {
                        TextField("session id", text: $vm.mirrorSessionId)
                        Button("Start Mirror") { vm.startMirror() }
                        Button("Stop Mirror") { vm.stopMirror() }
                    }

                    if !vm.mirrorLines.isEmpty {
                        Section("Incremental Updates") {
                            ForEach(Array(vm.mirrorLines.suffix(8).enumerated()), id: \.offset) { _, line in
                                Text(line)
                            }
                        }
                    }

                    Section("Actions") {
                        Button("Start Relay") { vm.startRelay() }
                        Button("Stop Relay") { vm.stopRelay() }
                    }
                }
                .navigationTitle("WatchAgent Bridge")
            }
        }
    }
}
