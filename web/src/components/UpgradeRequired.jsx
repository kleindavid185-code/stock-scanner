// Shown instead of a Claude-powered feature (Signals, AI Search, "Why it's
// moving") for free-tier users. No API call is made to reach this state --
// the page checks role and renders this before ever hitting the network.
export default function UpgradeRequired({ feature }) {
  return (
    <div className="upgrade-panel">
      <div className="upgrade-title">Upgrade required</div>
      <p className="disclaimer" style={{ marginBottom: 0 }}>
        {feature} is available on the paid tier. Contact the app owner to
        upgrade your account.
      </p>
    </div>
  );
}
