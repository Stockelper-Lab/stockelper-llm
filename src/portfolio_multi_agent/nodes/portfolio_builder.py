import numpy as np
from pydantic import BaseModel, Field
from portfolio_multi_agent.state import (
    Stock,
    MarketData,
    InvestorView,
    PortfolioWeight,
    PortfolioMetrics,
    PortfolioResult,
)
from scipy.optimize import minimize


class InputState(BaseModel):
    portfolio_list: list[Stock] = Field(default_factory=list)
    market_data_list: list[MarketData] = Field(default_factory=list)
    investor_views: list[InvestorView] = Field(default_factory=list)
    stock_scores: dict[str, float] = Field(default_factory=dict)
    risk_free_rate: float = Field(default=0.03)


class OutputState(BaseModel):
    portfolio_result: PortfolioResult | None = Field(default=None)


class PortfolioBuilder:
    name = "PortfolioBuilder"

    def __init__(
        self,
        tau: float = 0.025,
        max_weight: float = 0.3,
        min_weight: float = 0.0,
    ):
        """
        포트폴리오 빌더 (Black-Litterman 알고리즘 기반)

        Args:
            tau: 불확실성 스케일링 파라미터 (기본값: 0.025)
            max_weight: 개별 종목 최대 비중 (기본값: 0.3 = 30%)
            min_weight: 개별 종목 최소 비중 (기본값: 0.0 = 0%)
        """
        self.tau = tau
        self.max_weight = max_weight
        self.min_weight = min_weight

    def calculate_returns_covariance(
        self, market_data_list: list[MarketData]
    ) -> tuple[np.ndarray, int]:
        """
        수익률 공분산 행렬 계산

        Args:
            market_data_list: 시장 데이터 리스트

        Returns:
            (공분산 행렬, 데이터 개수)
        """
        n_stocks = len(market_data_list)
        if n_stocks == 0:
            return np.array([]), 0

        # 수익률 데이터를 행렬로 변환 (각 행은 종목, 각 열은 시점)
        returns_matrix = np.array([data.returns for data in market_data_list])

        # 공분산 행렬 계산 (일별 -> 연율화: 252 거래일 가정)
        cov_matrix = np.cov(returns_matrix) * 252

        return cov_matrix, n_stocks

    def calculate_market_weights(
        self, portfolio_list: list[Stock], stock_scores: dict[str, float]
    ) -> np.ndarray:
        """
        순위 점수 기반 시장 균형 가중치 계산

        Args:
            portfolio_list: 종목 리스트
            stock_scores: 각 종목의 순위 점수

        Returns:
            시장 균형 가중치 벡터
        """
        # 각 종목의 점수를 배열로 변환
        scores = np.array(
            [stock_scores.get(stock.code, 1.0) for stock in portfolio_list]
        )
        total_score = scores.sum()

        if total_score == 0:
            # 점수 정보가 없으면 균등 가중
            return np.ones(len(portfolio_list)) / len(portfolio_list)

        return scores / total_score

    def calculate_risk_aversion(
        self,
        cov_matrix: np.ndarray,
        market_weights: np.ndarray,
        risk_free_rate: float,
    ) -> float:
        """
        위험 회피 계수 계산

        Args:
            cov_matrix: 공분산 행렬
            market_weights: 시장 균형 가중치
            risk_free_rate: 무위험 이자율

        Returns:
            위험 회피 계수 delta
        """
        # 시장 포트폴리오의 분산
        market_variance = market_weights.T @ cov_matrix @ market_weights

        # 시장 프리미엄 가정 (일반적으로 5~8%)
        market_premium = 0.06

        # delta = (E[r_m] - r_f) / sigma_m^2
        delta = market_premium / market_variance

        return delta

    def calculate_implied_equilibrium_returns(
        self, delta: float, cov_matrix: np.ndarray, market_weights: np.ndarray
    ) -> np.ndarray:
        """
        시장 균형 초과 수익률 계산

        Args:
            delta: 위험 회피 계수
            cov_matrix: 공분산 행렬
            market_weights: 시장 균형 가중치

        Returns:
            균형 초과 수익률 벡터 pi
        """
        # pi = delta * Sigma * w_mkt
        pi = delta * cov_matrix @ market_weights
        return pi

    def construct_view_matrices(
        self, investor_views: list[InvestorView], n_stocks: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        투자자 뷰로부터 P, Q, Omega 행렬 구성

        Args:
            investor_views: 투자자 뷰 리스트
            n_stocks: 종목 개수

        Returns:
            (P 행렬, Q 벡터, Omega 행렬)
        """
        k = len(investor_views)  # 뷰의 개수

        if k == 0:
            # 뷰가 없으면 빈 행렬 반환
            return (
                np.zeros((0, n_stocks)),
                np.zeros(0),
                np.zeros((0, 0)),
            )

        # P 행렬: k x n (k개의 뷰, n개의 종목)
        P = np.zeros((k, n_stocks))
        # Q 벡터: k x 1
        Q = np.zeros(k)
        # Omega 행렬: k x k (대각 행렬)
        Omega = np.zeros((k, k))

        for i, view in enumerate(investor_views):
            # P 행렬: 해당 뷰가 적용되는 종목에 1 설정
            for idx in view.stock_indices:
                if 0 <= idx < n_stocks:
                    P[i, idx] = 1.0 / len(view.stock_indices)

            # Q 벡터: 예상 수익률
            Q[i] = view.expected_return

            # Omega 행렬: 신뢰도의 역수를 대각 원소로 설정
            # 신뢰도가 높을수록 불확실성이 낮음
            # confidence가 0에 가까우면 매우 불확실, 1에 가까우면 매우 확실
            if view.confidence > 0:
                Omega[i, i] = (1 - view.confidence) / view.confidence
            else:
                Omega[i, i] = 1e6  # 신뢰도가 0이면 매우 큰 불확실성

        return P, Q, Omega

    def calculate_posterior_returns(
        self,
        pi: np.ndarray,
        cov_matrix: np.ndarray,
        P: np.ndarray,
        Q: np.ndarray,
        Omega: np.ndarray,
    ) -> np.ndarray:
        """
        Black-Litterman 사후 초과 수익률 계산

        Args:
            pi: 균형 초과 수익률
            cov_matrix: 공분산 행렬
            P: 뷰 선택 행렬
            Q: 예상 수익률 벡터
            Omega: 뷰 불확실성 행렬

        Returns:
            사후 초과 수익률 벡터
        """
        n = len(pi)

        # 뷰가 없는 경우 균형 수익률 반환
        if len(Q) == 0:
            return pi

        # tau * Sigma
        tau_cov = self.tau * cov_matrix

        # [(tau*Sigma)^-1 + P^T * Omega^-1 * P]^-1
        inv_tau_cov = np.linalg.inv(tau_cov)
        inv_omega = np.linalg.inv(Omega)

        precision_matrix = inv_tau_cov + P.T @ inv_omega @ P
        posterior_cov = np.linalg.inv(precision_matrix)

        # mu_bl = posterior_cov * [(tau*Sigma)^-1 * pi + P^T * Omega^-1 * Q]
        mu_bl = posterior_cov @ (inv_tau_cov @ pi + P.T @ inv_omega @ Q)

        return mu_bl

    def optimize_portfolio(
        self,
        mu: np.ndarray,
        cov_matrix: np.ndarray,
        delta: float,
    ) -> np.ndarray:
        """
        최적 포트폴리오 가중치 계산

        Args:
            mu: 예상 초과 수익률
            cov_matrix: 공분산 행렬
            delta: 위험 회피 계수

        Returns:
            최적 가중치 벡터
        """
        n = len(mu)

        # 제약 조건 없는 최적해: w = (delta * Sigma)^-1 * mu
        weights = np.linalg.inv(delta * cov_matrix) @ mu

        # 제약 조건 적용: 최적화 문제로 재구성
        # minimize: 0.5 * w^T * Sigma * w - (mu / delta)^T * w
        # subject to: sum(w) = 1, min_weight <= w_i <= max_weight

        def objective(w):
            portfolio_variance = w.T @ cov_matrix @ w
            portfolio_return = mu.T @ w
            # 목적 함수: 위험 회피를 고려한 효용 함수
            return -portfolio_return + 0.5 * delta * portfolio_variance

        # 제약 조건: 가중치 합 = 1
        constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}

        # 경계 조건: 각 가중치는 min_weight ~ max_weight
        bounds = [(self.min_weight, self.max_weight) for _ in range(n)]

        # 초기값: 제약 조건 없는 최적해를 정규화
        if weights.sum() > 0:
            x0 = weights / weights.sum()
        else:
            x0 = np.ones(n) / n

        # 최적화 실행
        result = minimize(
            objective,
            x0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 1000},
        )

        if result.success:
            return result.x
        else:
            # 최적화 실패시 균등 가중 반환
            return np.ones(n) / n

    def calculate_portfolio_metrics(
        self,
        weights: np.ndarray,
        mu: np.ndarray,
        cov_matrix: np.ndarray,
        risk_free_rate: float,
    ) -> PortfolioMetrics:
        """
        포트폴리오 성과 지표 계산

        Args:
            weights: 포트폴리오 가중치
            mu: 예상 초과 수익률
            cov_matrix: 공분산 행렬
            risk_free_rate: 무위험 이자율

        Returns:
            포트폴리오 성과 지표
        """
        # 예상 수익률 (연율)
        expected_return = float(mu.T @ weights + risk_free_rate)

        # 변동성 (연율 표준편차)
        volatility = float(np.sqrt(weights.T @ cov_matrix @ weights))

        # 샤프 비율
        if volatility > 0:
            sharpe_ratio = (expected_return - risk_free_rate) / volatility
        else:
            sharpe_ratio = 0.0

        return PortfolioMetrics(
            expected_return=expected_return,
            volatility=volatility,
            sharpe_ratio=sharpe_ratio,
        )

    async def __call__(self, state: InputState) -> OutputState:
        """
        Black-Litterman 모델을 사용한 포트폴리오 최적화

        Args:
            state: 입력 상태 (종목 리스트, 시장 데이터, 투자자 뷰, 무위험 이자율)

        Returns:
            포트폴리오 최적화 결과
        """
        # 입력 검증
        if not state.portfolio_list or not state.market_data_list:
            return {"portfolio_result": None}

        # market_data가 있는 종목 코드 추출
        available_codes = {md.code for md in state.market_data_list}

        # portfolio_list 필터링 및 인덱스 매핑
        filtered_portfolio = []
        old_to_new_index = {}

        for old_idx, stock in enumerate(state.portfolio_list):
            if stock.code in available_codes:
                old_to_new_index[old_idx] = len(filtered_portfolio)
                filtered_portfolio.append(stock)

        # 필터링된 종목이 없으면 None 리턴
        if not filtered_portfolio:
            return {"portfolio_result": None}

        # market_data_list를 filtered_portfolio 순서에 맞게 정렬
        code_to_market_data = {md.code: md for md in state.market_data_list}
        filtered_market_data = [
            code_to_market_data[stock.code] for stock in filtered_portfolio
        ]

        # investor_views 필터링 및 인덱스 재조정
        filtered_views = []
        for view in state.investor_views:
            new_indices = [
                old_to_new_index[idx]
                for idx in view.stock_indices
                if idx in old_to_new_index
            ]
            if new_indices:
                filtered_views.append(
                    InvestorView(
                        stock_indices=new_indices,
                        expected_return=view.expected_return,
                        confidence=view.confidence,
                        reasoning=view.reasoning,
                    )
                )

        # stock_scores 필터링
        filtered_scores = {
            stock.code: state.stock_scores.get(stock.code, 1.0)
            for stock in filtered_portfolio
        }

        # 필터링된 데이터로 포트폴리오 구성

        # 1. 공분산 행렬 계산
        cov_matrix, n_stocks = self.calculate_returns_covariance(filtered_market_data)
        if n_stocks == 0:
            return {"portfolio_result": None}

        # 2. 시장 균형 가중치 계산 (순위 점수 기반)
        market_weights = self.calculate_market_weights(
            filtered_portfolio, filtered_scores
        )

        # 3. 위험 회피 계수 계산
        delta = self.calculate_risk_aversion(
            cov_matrix, market_weights, state.risk_free_rate
        )

        # 4. 시장 균형 초과 수익률 계산
        pi = self.calculate_implied_equilibrium_returns(
            delta, cov_matrix, market_weights
        )

        # 5. 투자자 뷰 행렬 구성
        P, Q, Omega = self.construct_view_matrices(filtered_views, n_stocks)

        # 6. Black-Litterman 사후 수익률 계산
        mu_bl = self.calculate_posterior_returns(pi, cov_matrix, P, Q, Omega)

        # 7. 최적 포트폴리오 가중치 계산
        optimal_weights = self.optimize_portfolio(mu_bl, cov_matrix, delta)

        # 8. 포트폴리오 성과 지표 계산
        metrics = self.calculate_portfolio_metrics(
            optimal_weights, mu_bl, cov_matrix, state.risk_free_rate
        )

        # 9. 종목별 reasoning 매핑 (investor_views에서 추출)
        stock_reasoning_map = {}
        for view in filtered_views:
            # 각 뷰는 하나 이상의 종목 인덱스를 가질 수 있음
            for idx in view.stock_indices:
                if idx < len(filtered_portfolio):
                    stock_code = filtered_portfolio[idx].code
                    # 같은 종목에 여러 뷰가 있을 수 있으므로, 첫 번째 것만 사용하거나 병합 가능
                    if stock_code not in stock_reasoning_map:
                        stock_reasoning_map[stock_code] = view.reasoning

        # 10. 결과 생성
        portfolio_weights = [
            PortfolioWeight(
                code=stock.code,
                name=stock.name,
                weight=float(weight),
                reasoning=stock_reasoning_map.get(stock.code, ""),
            )
            for stock, weight in zip(filtered_portfolio, optimal_weights)
        ]

        # 비중이 0보다 큰 종목만 필터링 (선택적)
        portfolio_weights = [w for w in portfolio_weights if w.weight > 0.001]

        portfolio_result = PortfolioResult(
            weights=portfolio_weights,
            metrics=metrics,
        )

        return {"portfolio_result": portfolio_result}
