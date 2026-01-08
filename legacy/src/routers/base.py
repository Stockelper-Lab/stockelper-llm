from fastapi import APIRouter

router = APIRouter(tags=["base"])

@router.get("/")
def read_root():
    """루트 엔드포인트"""
    return {"Hello": "World"}

@router.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy"} 