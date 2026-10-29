import AuthenticationServices
import SmartSchedulerKit
import SwiftUI

/// Google Calendar and Outlook accounts whose busy times captures avoid.
///
/// Sign-in runs in `ASWebAuthenticationSession`: the provider's own page in a
/// system browser sheet, so the app never sees the password, and the client
/// secret stays on the backend.
struct ConnectedCalendarsSection: View {
    @Environment(AppModel.self) private var model
    @Environment(\.webAuthenticationSession) private var webAuthenticationSession
    @State private var connecting: ExternalCalendarProvider?

    var body: some View {
        Section {
            ForEach(model.calendarAccounts) { account in
                HStack {
                    VStack(alignment: .leading) {
                        Text(account.provider.displayName)
                        Text(account.externalEmail ?? "Cuenta conectada")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if account.status != .active {
                        Button("Reconectar") { connect(account.provider) }
                            .font(.footnote)
                            .foregroundStyle(.orange)
                    }
                }
            }
            .onDelete { offsets in
                let accounts = offsets.map { model.calendarAccounts[$0] }
                Task {
                    for account in accounts {
                        await model.disconnectCalendar(account)
                    }
                }
            }

            ForEach(ExternalCalendarProvider.allCases) { provider in
                if let status = model.calendarProviders.first(where: { $0.provider == provider }), !status.configured {
                    // Shown until the backend .env has this provider's credentials.
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(provider.displayName): falta configurar el servidor")
                        Text("Completa \(status.missingSettings.joined(separator: ", ")) en .env (docs/calendar-credentials.md).")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                } else {
                    Button(connecting == provider ? "Conectando…" : "Conectar \(provider.displayName)") {
                        connect(provider)
                    }
                    .disabled(connecting != nil)
                }
            }

            if let message = model.calendarMessage {
                Text(message).font(.footnote).foregroundStyle(.secondary)
            }
        } header: {
            Text("Calendarios conectados")
        } footer: {
            Text("Smart Scheduler evita las horas ocupadas de estos calendarios al elegir hora. Solo lee inicio y fin de cada evento.")
        }
        .task { await model.loadCalendars() }
    }

    private func connect(_ provider: ExternalCalendarProvider) {
        Task {
            connecting = provider
            defer { connecting = nil }
            guard let url = await model.calendarAuthorizationURL(for: provider) else { return }
            do {
                let callback = try await webAuthenticationSession.authenticate(
                    using: url,
                    callbackURLScheme: CalendarConnectionResult.callbackScheme
                )
                await model.finishCalendarConnection(CalendarConnectionResult(callbackURL: callback))
            } catch ASWebAuthenticationSessionError.canceledLogin {
                return
            } catch {
                await model.finishCalendarConnection(.failed(error.localizedDescription))
            }
        }
    }
}
