import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import App from './App'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function pdfResponse(filename = 'AAPL_Equity_Research_Report.pdf'): Response {
  const blob = new Blob(['%PDF-1.7 mock'], { type: 'application/pdf' })
  return new Response(blob, {
    status: 200,
    headers: {
      'Content-Type': 'application/pdf',
      'Content-Disposition': `attachment; filename="${filename}"`,
    },
  })
}

describe('App', () => {
  it('validates empty query and shows a friendly form error', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValue(jsonResponse({ riskProfiles: ['defensive', 'balanced', 'aggressive'] }))

    render(<App />)

    await userEvent.click(screen.getByRole('button', { name: /generate report/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Please enter a company name or ticker symbol.',
    )
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('shows loading state and disables submit controls while generating', async () => {
    const fetchMock = vi.mocked(fetch)
    let resolveGenerate!: (response: Response) => void
    const generatePromise = new Promise<Response>((resolve) => {
      resolveGenerate = resolve
    })
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ riskProfiles: ['defensive', 'balanced', 'aggressive'] }))
      .mockReturnValueOnce(generatePromise)

    render(<App />)

    const queryInput = screen.getByLabelText(/company \/ ticker/i)
    const riskSelect = screen.getByLabelText(/risk profile/i)
    const submitButton = screen.getByRole('button', { name: /generate report/i })

    await userEvent.type(queryInput, 'AAPL')
    await userEvent.click(submitButton)

    expect(screen.getByRole('button', { name: /generating/i })).toBeDisabled()
    expect(queryInput).toBeDisabled()
    expect(riskSelect).toBeDisabled()

    resolveGenerate(pdfResponse())

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('Success. Download started'),
    )
  })

  it('downloads pdf blob and parses filename from content-disposition', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ riskProfiles: ['defensive', 'balanced', 'aggressive'] }))
      .mockResolvedValueOnce(pdfResponse('AAPL_Equity_Research_Report.pdf'))

    const createObjectUrlSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:download')
    const revokeObjectUrlSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

    render(<App />)

    await userEvent.type(screen.getByLabelText(/company \/ ticker/i), 'AAPL')
    await userEvent.click(screen.getByRole('button', { name: /generate report/i }))

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(
        'AAPL_Equity_Research_Report.pdf',
      ),
    )
    expect(createObjectUrlSpy).toHaveBeenCalled()
    expect(clickSpy).toHaveBeenCalledTimes(1)
    expect(revokeObjectUrlSpy).toHaveBeenCalledWith('blob:download')
  })

  it('renders backend failure message in an error banner', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ riskProfiles: ['defensive', 'balanced', 'aggressive'] }))
      .mockResolvedValueOnce(
        jsonResponse({ detail: 'Market data provider is temporarily unavailable.' }, 503),
      )

    render(<App />)

    await userEvent.type(screen.getByLabelText(/company \/ ticker/i), 'AAPL')
    await userEvent.click(screen.getByRole('button', { name: /generate report/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Market data provider is temporarily unavailable.',
    )
  })
})
