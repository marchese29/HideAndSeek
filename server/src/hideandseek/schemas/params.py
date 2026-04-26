"""Question parameter schemas — shared by response schemas and snapshot builders."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from hideandseek_models.types import QuestionType

if TYPE_CHECKING:
    from hideandseek_models.question import Question as QuestionModel


class RadarParamsResponse(BaseModel):
    """Parameters for a radar question."""

    type: Literal['radar'] = 'radar'
    radius: float = Field(description='Radar radius in convention units.')


class ThermometerParamsResponse(BaseModel):
    """Parameters for a thermometer question."""

    type: Literal['thermometer'] = 'thermometer'
    min_travel: float = Field(description='Minimum travel distance in convention units.')


class FeatureResolution(BaseModel):
    """Resolution result for one player's feature lookup."""

    feature_id: str = Field(description='Stable identifier of the resolved feature.')
    name: str = Field(description='Human-readable name.')
    distance: float = Field(description='Distance in convention units.')


class FeatureParamsResponse(BaseModel):
    """Parameters for a matching or measuring question."""

    type: Literal['matching', 'measuring']
    category: str = Field(description='Feature category.')
    feature_class: int | None = Field(
        default=None, description='Feature class tier, if applicable.'
    )
    source: str = Field(description='Data source (e.g. map_data).')
    seeker_resolution: FeatureResolution = Field(description='Seeker feature resolution.')
    hider_resolution: FeatureResolution | None = Field(
        default=None, description='Hider feature resolution (populated at answer time).'
    )


class PhotoParamsResponse(BaseModel):
    """Parameters for a photo question."""

    type: Literal['photo'] = 'photo'
    subject: str = Field(description='Photo subject identifier.')


class TentacleParamsResponse(BaseModel):
    """Parameters for a tentacles question."""

    type: Literal['tentacles'] = 'tentacles'
    category: str = Field(description='POI category.')
    poi_ids: list[str] = Field(description='Stable IDs of POIs within the distance circle.')
    poi_names: list[str] = Field(description='Human-readable names, matching poi_ids order.')
    hit: bool | None = Field(
        default=None, description='True if hider was in range (populated at answer time).'
    )
    hider_feature_id: str | None = Field(
        default=None, description='Stable ID of the nearest POI on hit (populated at answer time).'
    )


QuestionParamsResponse = (
    RadarParamsResponse
    | ThermometerParamsResponse
    | FeatureParamsResponse
    | TentacleParamsResponse
    | PhotoParamsResponse
)


def build_question_params(question: QuestionModel) -> QuestionParamsResponse:
    """Build typed parameters from the question's param relationships."""
    if question.question_type == QuestionType.radar:
        rp = question.radar_params
        assert rp is not None
        return RadarParamsResponse(radius=rp.radius)
    elif question.question_type == QuestionType.thermometer:
        tp = question.thermometer_params
        assert tp is not None
        return ThermometerParamsResponse(min_travel=tp.min_travel)
    elif question.question_type == QuestionType.photo:
        pp = question.photo_params
        assert pp is not None
        return PhotoParamsResponse(subject=str(pp.subject))
    elif question.question_type == QuestionType.tentacles:
        tp = question.tentacle_params
        assert tp is not None
        return TentacleParamsResponse(
            category=str(tp.category),
            poi_ids=list(tp.poi_ids),
            poi_names=list(tp.poi_names),
            hit=tp.hit,
            hider_feature_id=tp.hider_feature_id,
        )
    else:
        fp = question.feature_params
        assert fp is not None
        seeker_res = FeatureResolution(
            feature_id=fp.seeker_feature_id,
            name=fp.seeker_feature_name,
            distance=fp.seeker_distance,
        )
        hider_res = None
        if fp.hider_feature_id is not None:
            hider_res = FeatureResolution(
                feature_id=fp.hider_feature_id,
                name=fp.hider_feature_name or '',
                distance=fp.hider_distance or 0.0,
            )
        return FeatureParamsResponse(
            type=question.question_type,  # type: ignore[arg-type]
            category=str(fp.category),
            feature_class=fp.feature_class,
            source=fp.source,
            seeker_resolution=seeker_res,
            hider_resolution=hider_res,
        )
