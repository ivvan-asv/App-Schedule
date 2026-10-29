import SwiftUI

@main
struct SmartSchedulerApp: App {
    @State private var model = AppModel.shared
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .task { await model.start() }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                Task { await model.flushPending() }
            }
        }
        #if os(iOS)
        .backgroundTask(.appRefresh(AppServices.backgroundFlushTaskID)) {
            await AppModel.shared.flushPending()
        }
        #endif
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        @Bindable var model = model
        TabView(selection: $model.selectedTab) {
            CaptureView()
                .tabItem { Label("Capturar", systemImage: "mic.fill") }
                .tag(AppTab.capture)
            AgendaView()
                .tabItem { Label("Agenda", systemImage: "calendar") }
                .tag(AppTab.agenda)
            SettingsView()
                .tabItem { Label("Ajustes", systemImage: "gearshape") }
                .tag(AppTab.settings)
        }
        // Dictation can only start once the app is in the foreground, which
        // is not yet the case when DictateCaptureIntent runs.
        .task(id: DictationTrigger(requested: model.dictationRequested, phase: scenePhase)) {
            if scenePhase == .active {
                model.consumeDictationRequest()
            }
        }
    }
}

private struct DictationTrigger: Equatable {
    let requested: Bool
    let phase: ScenePhase
}
