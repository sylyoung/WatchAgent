import SwiftUI

struct ContentView: View {
    @StateObject var viewModel: SessionViewModel
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    // Header
                    HStack {
                        Circle()
                            .fill(viewModel.relayConnected ? Color.green : Color.red)
                            .frame(width: 8, height: 8)
                        Text(viewModel.relayConnected ? "relay" : "no relay")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        NavigationLink {
                            VoiceSettingsView()
                        } label: {
                            Image(systemName: "speaker.wave.2.circle")
                                .font(.body)
                        }
                        .buttonStyle(.plain)
                    }

                    // Quick Skills – main interaction entry (3x2 grid)
                    LazyVGrid(columns: [
                        GridItem(.flexible()),
                        GridItem(.flexible()),
                        GridItem(.flexible())
                    ], spacing: 6) {
                        ForEach(QuickSkill.allCases) { skill in
                            Button(skill.rawValue) {
                                viewModel.trigger(skill: skill)
                            }
                            .buttonStyle(.bordered)
                            .font(.caption2)
                        }
                    }

                    // Voice input button / live recording indicator
                    if viewModel.isListening {
                        VStack(spacing: 4) {
                            Text(viewModel.transcript.isEmpty ? "正在听..." : viewModel.transcript)
                                .font(.caption2)
                                .foregroundStyle(.primary)
                                .lineLimit(3)
                            Button {
                                viewModel.stopListeningAndSend()
                            } label: {
                                Label("停止", systemImage: "stop.fill")
                            }
                            .buttonStyle(.bordered)
                            .tint(.red)
                            .font(.caption2)
                            .watchPrimaryActionGestureShortcut()
                        }
                    } else {
                        Button {
                            viewModel.presentDictation()
                        } label: {
                            Label("语音指令", systemImage: "mic.fill")
                        }
                        .buttonStyle(.bordered)
                        .font(.caption2)
                        .watchPrimaryActionGestureShortcut()
                    }

                    Divider()

                    // Latest speech / result
                    Text("汇总信息")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text(viewModel.latestSpeech)
                        .font(.footnote)

                    // Stream updates
                    if !viewModel.streamLines.isEmpty {
                        Text("异步信息(播报中)")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        ForEach(Array(viewModel.streamLines.suffix(6).enumerated()), id: \.offset) { _, line in
                            Text("• \(line)")
                                .font(.caption2)
                        }
                    }

                    if let errorText = viewModel.errorText {
                        Text(errorText)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }

                    if !viewModel.speechDiag.isEmpty {
                        Text(viewModel.speechDiag)
                            .font(.caption2)
                            .foregroundStyle(.orange)
                    }

                    // Approval cards
                    if !viewModel.cards.isEmpty {
                        Divider()
                        Text("待确认（剩余 \(viewModel.pendingCardCount) 条）")
                            .font(.caption2)
                            .foregroundStyle(.secondary)

                        if let card = viewModel.currentCard {
                            approvalCardView(card)
                        }
                    }
                }
                .padding(10)
            }
            .navigationBarTitleDisplayMode(.inline)
        }
        .onAppear {
            viewModel.handleLaunch()
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                viewModel.handleForeground()
            } else {
                viewModel.handleBackground()
            }
        }
    }

    @ViewBuilder
    private func approvalCardView(_ card: ActionCard) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            if card.isVoiceRejectOnly {
                HStack {
                    if let progress = viewModel.codexProgressLabel {
                        Text(progress)
                    }
                    if let thread = viewModel.codexThreadLabel {
                        Text(thread)
                    }
                }
                .font(.caption2)
                .foregroundStyle(.secondary)
            }

            Text(card.title).font(.footnote).bold()
            Text(card.detail).font(.caption2)
                .foregroundStyle(.secondary)

            if card.isVoiceRejectOnly {
                if let session = viewModel.codexSessionLabel {
                    Text(session)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }

            VStack(spacing: 6) {
                if !viewModel.isRejectDecisionActive(for: card) {
                    Button("Yes") {
                        viewModel.approve(card: card, mode: .gesture)
                    }
                    .buttonStyle(.borderedProminent)
                    .frame(maxWidth: .infinity)
                    .tint(.green)
                    .watchPrimaryActionGestureShortcut()

                    Button("No") {
                        viewModel.beginRejectDecision(card: card)
                    }
                    .buttonStyle(.bordered)
                    .frame(maxWidth: .infinity)
                } else {
                    Button("直接拒绝") {
                        viewModel.rejectWithoutFollowup(card: card)
                    }
                    .buttonStyle(.bordered)
                    .frame(maxWidth: .infinity)

                    Button("语音补充") {
                        viewModel.rejectWithVoiceFollowup(card: card)
                    }
                    .buttonStyle(.borderedProminent)
                    .frame(maxWidth: .infinity)
                    .tint(.orange)
                }
            }

            Text(viewModel.isRejectDecisionActive(for: card)
                 ? "第二步：直接拒绝，或开启语音补充。"
                 : "Double Tap 同意，或点 No 选择拒绝方式。")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding(8)
        .background(Color.gray.opacity(0.15))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

private struct WatchPrimaryActionGestureShortcutModifier: ViewModifier {
    @ViewBuilder
    func body(content: Content) -> some View {
        if #available(watchOS 11.0, *) {
            content.handGestureShortcut(.primaryAction)
        } else {
            content
        }
    }
}

private extension View {
    func watchPrimaryActionGestureShortcut() -> some View {
        modifier(WatchPrimaryActionGestureShortcutModifier())
    }
}
