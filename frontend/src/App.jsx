import { useEffect, useMemo, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

const tabs = [
  { id: 'home', label: 'Головна' },
  { id: 'earn', label: 'Заробіток' },
  { id: 'wallet', label: 'Гаманець' }
]

export default function App() {
  const [activeTab, setActiveTab] = useState('home')
  const [user, setUser] = useState(null)
  const [offers, setOffers] = useState([])
  const [referrals, setReferrals] = useState(null)
  const [wallet, setWallet] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [withdrawOpen, setWithdrawOpen] = useState(false)
  const [withdrawAmount, setWithdrawAmount] = useState('')
  const [withdrawDetails, setWithdrawDetails] = useState('')
  const [statusMessage, setStatusMessage] = useState('')

  const headers = useMemo(() => {
    if (!user) return {}
    return { 'X-User-Id': String(user.id) }
  }, [user])

  useEffect(() => {
    async function init() {
      try {
        if (window.Telegram?.WebApp) {
          window.Telegram.WebApp.ready()
          window.Telegram.WebApp.expand()
        }
        const initData = window.Telegram?.WebApp?.initData || ''
        if (!initData) {
          setError('Не вдалося отримати дані Telegram WebApp. Відкрийте застосунок через Telegram.')
          setLoading(false)
          return
        }
        const authRes = await fetch(`${API_BASE}/auth/telegram`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ initData })
        })
        if (!authRes.ok) {
          throw new Error('Помилка авторизації в Telegram')
        }
        const authData = await authRes.json()
        setUser(authData)
      } catch (err) {
        setError('Помилка авторизації. Спробуйте пізніше.')
      } finally {
        setLoading(false)
      }
    }

    init()
  }, [])

  useEffect(() => {
    if (!user) return
    async function loadData() {
      try {
        const [offersRes, referralsRes, walletRes] = await Promise.all([
          fetch(`${API_BASE}/offers`),
          fetch(`${API_BASE}/referrals`, { headers }),
          fetch(`${API_BASE}/wallet`, { headers })
        ])
        if (offersRes.ok) setOffers(await offersRes.json())
        if (referralsRes.ok) setReferrals(await referralsRes.json())
        if (walletRes.ok) setWallet(await walletRes.json())
      } catch (err) {
        setError('Не вдалося завантажити дані.')
      }
    }
    loadData()
  }, [user, headers])

  const computedReferralLink = user
    ? `https://t.me/${import.meta.env.VITE_BOT_USERNAME || ''}?start=ref_${user.telegram_id}`
    : ''

  async function handlePlay() {
    if (!user) return
    setStatusMessage('')
    const res = await fetch(`${API_BASE}/game/play`, {
      method: 'POST',
      headers
    })
    if (!res.ok) {
      setStatusMessage('Гра доступна після депозиту.')
      return
    }
    const data = await res.json()
    setStatusMessage(`Вам нараховано ${data.added_pro} PRO#`) 
    setWallet((prev) =>
      prev ? { ...prev, balance_pro: data.balance_pro, balance_usd: data.balance_pro / 10000 } : prev
    )
  }

  async function handleWithdraw(event) {
    event.preventDefault()
    if (!withdrawAmount || !withdrawDetails) {
      setStatusMessage('Заповніть суму та реквізити.')
      return
    }
    const res = await fetch(`${API_BASE}/withdraw`, {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount_pro: Number(withdrawAmount), details: withdrawDetails })
    })
    if (!res.ok) {
      setStatusMessage('Помилка виведення.')
      return
    }
    setStatusMessage('Заявку на виведення прийнято.')
    setWithdrawOpen(false)
    setWithdrawAmount('')
    setWithdrawDetails('')
    const walletRes = await fetch(`${API_BASE}/wallet`, { headers })
    if (walletRes.ok) setWallet(await walletRes.json())
  }

  function copyReferral() {
    navigator.clipboard.writeText(computedReferralLink)
    setStatusMessage('Посилання скопійовано!')
  }

  if (loading) {
    return <div className="container">Завантаження...</div>
  }

  return (
    <div className="container">
      <header className="header">
        <div>
          <h1>GoodCasino</h1>
          <p>Вітаємо у Telegram WebApp казино!</p>
        </div>
      </header>

      {error && <div className="error">{error}</div>}
      {statusMessage && <div className="status">{statusMessage}</div>}

      <nav className="tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={activeTab === tab.id ? 'tab active' : 'tab'}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {activeTab === 'home' && (
        <section className="panel">
          <h2>Головна</h2>
          <p>Баланс: {wallet?.balance_pro ?? 0} PRO#</p>
          <button className="primary" onClick={handlePlay}>
            Грати (+50k PRO#)
          </button>
          <div className="offers">
            <h3>Офери</h3>
            {offers.length === 0 && <p>Поки що немає оферів.</p>}
            {offers.map((offer) => (
              <div key={offer.id} className="card">
                <div>
                  <strong>{offer.title}</strong>
                  <p>Нагорода: {offer.reward_pro} PRO#</p>
                </div>
                <a className="link" href={offer.link} target="_blank" rel="noreferrer">
                  Перейти до офера
                </a>
              </div>
            ))}
          </div>
        </section>
      )}

      {activeTab === 'earn' && (
        <section className="panel">
          <h2>Заробіток</h2>
          <p>Усього рефералів: {referrals?.total_referrals ?? 0}</p>
          <p>З депозитом: {referrals?.referrals_with_deposit ?? 0}</p>
          <div className="referral-box">
            <label>Реферальне посилання</label>
            <input value={computedReferralLink} readOnly />
            <button onClick={copyReferral}>Скопіювати</button>
          </div>
        </section>
      )}

      {activeTab === 'wallet' && (
        <section className="panel">
          <h2>Гаманець</h2>
          <p>Баланс PRO#: {wallet?.balance_pro ?? 0}</p>
          <p>Баланс USD: {wallet?.balance_usd ?? 0}</p>
          <button className="primary" onClick={() => setWithdrawOpen(true)}>
            Вивести кошти
          </button>
        </section>
      )}

      {withdrawOpen && (
        <div className="modal">
          <div className="modal-content">
            <h3>Запит на виведення</h3>
            <form onSubmit={handleWithdraw}>
              <label>Сума PRO#</label>
              <input
                type="number"
                value={withdrawAmount}
                onChange={(event) => setWithdrawAmount(event.target.value)}
              />
              <label>Реквізити / коментар</label>
              <textarea
                value={withdrawDetails}
                onChange={(event) => setWithdrawDetails(event.target.value)}
              />
              <div className="modal-actions">
                <button type="button" onClick={() => setWithdrawOpen(false)}>
                  Скасувати
                </button>
                <button type="submit" className="primary">
                  Надіслати
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
