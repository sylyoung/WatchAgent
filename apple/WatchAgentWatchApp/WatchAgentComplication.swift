import WidgetKit
import SwiftUI

struct SimpleTimelineEntry: TimelineEntry {
    let date: Date
}

struct SimpleTimelineProvider: TimelineProvider {
    func placeholder(in context: Context) -> SimpleTimelineEntry {
        SimpleTimelineEntry(date: Date())
    }

    func getSnapshot(in context: Context, completion: @escaping (SimpleTimelineEntry) -> Void) {
        completion(SimpleTimelineEntry(date: Date()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<SimpleTimelineEntry>) -> Void) {
        let entry = SimpleTimelineEntry(date: Date())
        let timeline = Timeline(entries: [entry], policy: .after(Date().addingTimeInterval(3600)))
        completion(timeline)
    }
}

struct WatchAgentComplication: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(
            kind: "WatchAgentQuickLaunch",
            provider: SimpleTimelineProvider()
        ) { _ in
            VStack {
                Image(systemName: "brain.head.profile")
                Text("WatchAgent")
                    .font(.caption2)
            }
            .widgetURL(URL(string: "watchagent://launch"))
        }
        .configurationDisplayName("WatchAgent")
        .description("快速启动 WatchAgent")
        .supportedFamilies([.accessoryCircular, .accessoryRectangular, .accessoryCorner])
    }
}
